# denyhosts sync server
# Copyright (C) 2016 Jan-Pascal van Best <janpascal@vanbest.org>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
import json
import os.path
import xmlrpclib
from xmlrpclib import ServerProxy

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.internet.threads  import deferToThread

import libnacl.public
import libnacl.utils

import __init__
import config
import controllers

_own_key = None

@inlineCallbacks
def send_update(client_ip, timestamp, hosts):
    for peer in config.peers:
        logging.debug("Sending update to peer {}".format(peer))
        logging.debug("peer: {}".format(peer))
        data = {
            "client_ip": client_ip,
            "timestamp": timestamp,
            "hosts": hosts
        }
        data_json = json.dumps(data)
        crypted = _peer_boxes[peer].encrypt(data_json)
        base64 = crypted.encode('base64')

        server = yield deferToThread(ServerProxy, peer)
        yield deferToThread(server.peering_update, _own_key.pk.encode('hex'), base64)

@inlineCallbacks
def handle_update(peer_key, update):
    peer = None
    for _peer in config.peers:
        if config.peers[_peer] == peer_key:
            peer = _peer
            break
    if peer is None:
        logging.warning("Got update from unknown peer with key {}".format(peer_key.encode('hex')))
        raise Exception("Unknown key {}".format(peer_key.encode('hex')))

    # Critical point: use our own key, instead of the one supplied by the peer
    json_data = _peer_boxes[peer].decrypt(update)
    data = json.loads(json_data)

    hosts = data["hosts"]
    client_ip = data["client_ip"]
    timestamp = data["timestamp"]

    yield controllers.handle_report_from_client(client_ip, timestamp, hosts)

def list_peers(peer_key, please):
    peer = None
    for _peer in config.peers:
        if config.peers[_peer] == peer_key:
            peer = _peer
            break
    if peer is None:
        logging.warning("Got list_peer request from unknown peer with key {}".format(peer_key.encode('hex')))
        raise Exception("Unknown key {}".format(peer_key.encode('hex')))

    # Critical point: use our own key, instead of the one supplied by the peer
    logging.debug("Listing peers, requested by {}".format(peer))
    data = _peer_boxes[peer].decrypt(please)
    if data != "please":
        logging.warning("Request for list_peers is something else than please: {}".format(data))
        raise Exception("Illegal request {}".format(data))

    return {
            "server_version": __init__.version,
            "peers": {
                peer: config.peers[peer].encode('hex') 
                for peer in config.peers
            }
    }

def load_keys():
    global _own_key
    global _peer_boxes

    try:
        _own_key = libnacl.utils.load_key(config.key_file)
    except:
        logging.info("No private key yet, creating one in {}".format(config.key_file))
        _own_key = libnacl.public.SecretKey()
        _own_key.save(config.key_file)

    _peer_boxes = {
        peer: 
        libnacl.public.Box(_own_key.sk, libnacl.public.PublicKey(config.peers[peer]))
        for peer in config.peers
    }

    logging.debug("Configured peers: {}".format(config.peers))

def check_peers():
    """ Connect to all configured peers. Check if they are reachable, and if their
    list of peers and associated keys conforms to mine """
    success = True
    for peer in config.peers:
        print("Examining peer {}...".format(peer))
        peer_server = ServerProxy(peer)
        try:
            response = peer_server.list_peers(_own_key.pk.encode('hex'), _peer_boxes[peer].encrypt('please').encode('base64'))
        except Exception, e:
            print("Error requesting peer list from {} (maybe it's down, or it doesn't know my key!)".format(peer))
            print("Error message: {}".format(e))
            success = False
            continue

        print("    Peer version: {}".format(response["server_version"]))
        peer_list = response["peers"]

        # peer list should contain all the peers I know, except for the peer I'm asking, but including myself
        seen_peers = set()
        for other_peer in config.peers:
            if other_peer == peer:
                continue
            if other_peer not in peer_list:
                print("    Peer {} does not know peer {}!".format(peer, other_peer))
                success = False
                continue
            if config.peers[other_peer] != peer_list[other_peer].decode('hex'):
                print("    Peer {} knows peer {} but with key {} instead of {}!".format(peer, other_peer, peer_list[other_peer], config.peers[other_peer].encode('hex')))
                success = False
                continue
            print("    Common peer (OK): {}".format(other_peer))
            seen_peers.add(other_peer)

        # Any keys not seen should be my own
        own_key_seen = False
        for other_peer in peer_list:
            if other_peer in seen_peers:
                continue
            if peer_list[other_peer].decode('hex') == _own_key.pk:
                own_key_seen = True
                print("    Peer {} knows me as {} (OK)".format(peer, other_peer))
                continue
            print("    Peer {} knows about (to me) unknown peer {} with key {}!".format(peer, other_peer, peer_list[other_peer]))
            success = False

        if not own_key_seen:
            print("    Peer {} does not know about me!")
            success = False

    if success:
        print("All peer servers configured correctly")
    else:
        print("Inconsistent peer server configuration, check all configuration files!")

    return success

        




# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
