# -*- coding: utf-8 -*-

# Copyright (c) 2018-2022 The Particl Core developers
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.

import os
import time
import decimal
import hashlib
import threading
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
from .util import (
    COIN,
    json,
    makeInt,
    format8,
    format16,
)


class HttpHandler(BaseHTTPRequestHandler):
    def page_error(self, error_str):
        content = '<!DOCTYPE html><html lang="en">\n<head>' \
            + '<meta charset="UTF-8">' \
            + '<title>Particl Stake Pool Error</title></head>' \
            + '<body>' \
            + '<p>Error: ' + error_str + '</p>' \
            + '<p><a href=\'/\'>home</a></p>' \
            + '</body></html>'
        return bytes(content, 'UTF-8')

    def js_error(self, error_str):
        error_str_json = json.dumps({'error': error_str})
        return bytes(error_str_json, 'UTF-8')

    def js_address(self, urlSplit):
        if len(urlSplit) < 4:
            raise ValueError('Must specify address')
        address_str = urlSplit[3]
        stakePool = self.server.stakePool
        return bytes(json.dumps(stakePool.getAddressSummary(address_str)), 'UTF-8')

    def js_metrics(self, urlSplit):
        stakePool = self.server.stakePool
        if len(urlSplit) > 3:
            code_str = urlSplit[3]
            hashed = hashlib.sha256(str(code_str + self.server.management_key_salt).encode('utf-8')).hexdigest()
            if not hashed == self.server.management_key_hash:
                raise ValueError('Unknown argument')
            return bytes(json.dumps(stakePool.rebuildMetrics()), 'UTF-8')
        return bytes(json.dumps(stakePool.getMetrics()), 'UTF-8')

    def js_pending(self, urlSplit):
        stakePool = self.server.stakePool
        if len(urlSplit) > 3:
            code_str = urlSplit[3]
            hashed = hashlib.sha256(str(code_str + self.server.management_key_salt).encode('utf-8')).hexdigest()
            if not hashed == self.server.management_key_hash:
                raise ValueError('Unknown argument')
            return bytes(json.dumps(stakePool.getPending(True)), 'UTF-8')
        return bytes(json.dumps(stakePool.getPending()), 'UTF-8')

    def js_index(self, urlSplit):
        return bytes(json.dumps(self.server.stakePool.getSummary()), 'UTF-8')

    def page_config(self, urlSplit):
        settings_path = os.path.join(self.server.stakePool.dataDir, 'stakepool.json')

        if not os.path.exists(settings_path):
            raise ValueError('Settings file not found.')

        with open(settings_path) as fs:
            settings = json.load(fs)
        settings['particlbindir'] = '...'
        settings['particldatadir'] = '...'
        settings['poolownerwithdrawal'] = '...'
        settings['rpcauth'] = '...'
        settings['rpchost'] = '...'
        settings['zmqhost'] = '...'
        settings['htmlhost'] = '...'
        settings.pop('management_key_salt', None)
        settings.pop('management_key_hash', None)
        return bytes(json.dumps(settings, indent=4), 'UTF-8')

    def page_address(self, urlSplit):
        if len(urlSplit) < 3:
            raise ValueError('Must specify address')

        address_str = urlSplit[2]
        stakePool = self.server.stakePool
        summary = stakePool.getAddressSummary(address_str)

        content = '<!DOCTYPE html><html lang="en">\n<head>' \
            + '<meta charset="UTF-8">' \
            + '<title>Particl Stake Pool Address </title></head>' \
            + '<body>' \
            + '<h2>Spend Address ' + address_str + '</h2>' \
            + '<h4>Pool Address ' + stakePool.poolAddr + '</h4>'

        if 'accumulated' in summary:
            content += '<table>' \
                + '<tr><td>Accumulated:</td><td>' + format16(summary['accumulated']) + '</td></tr>' \
                + '<tr><td>Payout Pending:</td><td>' + format8(summary['rewardpending']) + '</td></tr>' \
                + '<tr><td>Paid Out:</td><td>' + format8(summary['rewardpaidout']) + '</td></tr>' \
                + '<tr><td>Last Total Staking:</td><td>' + format8(summary['laststaking']) + '</td></tr>' \
                + '<tr><td>Current Total in Pool:</td><td>' + format8(summary['currenttotal']) + '</td></tr>' \
                + '</table>'
        else:
            content += '<table>' \
                + '<tr><td>Current Total in Pool:</td><td>' + format8(summary['currenttotal']) + '</td></tr>' \
                + '</table>'

        content += '<p><a href=\'/\'>home</a></p></body></html>'
        return bytes(content, 'UTF-8')

    def page_voting_info(self, urlSplit):
        voting_settings = self.server.stakePool.getVotingInfo()

        vote_settings_content = ''
        for r in voting_settings:
            set_at = time.strftime('%Y-%m-%d %H-%M-%S %z', time.gmtime(int(r['added'])))
            vote_settings_content += '<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(r['proposal'], r['option'], r['from_height'], r['to_height'], set_at)

        content = '<!DOCTYPE html><html lang="en">\n<head>' \
            + '<meta charset="UTF-8">' \
            + '<title>Particl Stake Pool Voting Settings</title></head>' \
            + '<style>table, th, td {border: 1px solid black;border-collapse: collapse;}</style>' \
            + '<body>' \
            + '<h2>Particl Stake Pool Voting Settings</h2>' \
            + '<table>' \
            + '<tr><th>Proposal</th><th>Option</th><th>Height From</th><th>Height To</th><th>Set At</th></tr>' \
            + vote_settings_content \
            + '</table>' \
            + '<p><a href=\'/\'>home</a></p></body></html>'
        return bytes(content, 'UTF-8')

    def page_version(self):
        versions = self.server.stakePool.getVersions()

        content = '<!DOCTYPE html><html lang="en">\n<head>' \
            + '<meta charset="UTF-8">' \
            + '<title>Particl Stake Pool Version</title></head>' \
            + '<body>' \
            + '<h2>Particl Stake Pool Version</h2>' \
            + '<p>' \
            + 'Pool Version: ' + versions['pool'] + '<br/>' \
            + 'Core Version: ' + versions['core'] + '<br/>' \
            + '</p>' \
            + '<p><a href=\'/\'>home</a></p></body></html>'
        return bytes(content, 'UTF-8')

    def page_index(self):
        stakePool = self.server.stakePool
        summary = stakePool.getSummary()

        content = '<!DOCTYPE html><html lang="en">\n<head>' \
            + '<meta charset="UTF-8">' \
            + '<title>Particl Stake Pool</title></head>' \
            + '<body>' \
            + '<h2>Particl Stake Pool</h2>' \
            + '<p>' \
            + 'Mode: ' + summary['poolmode'] + '<br/>' \
            + 'Pool Address: ' + stakePool.poolAddr + '<br/>' \
            + 'Pool Fee: ' + str(stakePool.poolFeePercent) + '%<br/>' \
            + 'Stake Bonus: ' + str(stakePool.stakeBonusPercent) + '%<br/>' \
            + 'Payout Threshold: ' + format8(stakePool.payoutThreshold) + '<br/>' \
            + 'Blocks Between Payment Runs: ' + str(stakePool.minBlocksBetweenPayments) + '<br/>' \
            + 'Minimum output value: ' + format8(stakePool.minOutputValue) + '<br/>'

        if stakePool.smsg_fee_rate_target is not None:
            content += 'SMSG fee rate target: ' + format8(makeInt(stakePool.smsg_fee_rate_target)) + '<br/>'

        content += '</p><p>' \
            + 'Synced Height: ' + str(summary['poolheight']) + '<br/>' \
            + 'Blocks Found: ' + str(summary['blocksfound']) + '<br/>' \
            + 'Total Disbursed: ' + format8(summary['totaldisbursed']) + '<br/>' \
            + 'Last Payment Run: ' + str(summary['lastpaymentrunheight']) + '<br/>' \
            + '<br/>' \
            + 'Total Pool Rewards: ' + format8(summary['poolrewardtotal']) + '<br/>' \
            + 'Total Pool Fees: ' + format8(summary['poolfeestotal']) + '<br/>' \
            + 'Total Pool Rewards Withdrawn: ' + format8(summary['poolwithdrawntotal']) + '<br/>' \
            + '<br/>' \
            + 'Total Pooled Coin: ' + format8(int(decimal.Decimal(summary['watchonlytotalbalance']) * COIN)) + '<br/>' \
            + 'Currently Staking: ' + format8(summary['stakeweight']) + '<br/>' \
            + '</p>'

        content += '<br/><h3>Recent Blocks</h3><table><tr><th>Height</th><th>Block Hash</th><th>Block Reward</th><th>Total Coin Staking</th></tr>'
        for b in summary['lastblocks']:
            content += '<tr><td>' + str(b[0]) + '</td><td>' + b[1] + '</td><td>' + format8(b[2]) + '</td><td>' + format8(b[3]) + '</td></tr>'
        content += '</table>'

        content += '<br/><h3>Pending Payments</h3><table><tr><th>Txid</th><th>Disbursed</th></tr>'
        for b in summary['pendingpayments']:
            content += '<tr><td>' + b[0] + '</td><td>' + format8(b[1]) + '</td></tr>'
        content += '</table>'

        content += '<br/><h3>Last Payments</h3><table><tr><th>Height</th><th>Txid</th><th>Disbursed</th></tr>'
        for b in summary['lastpayments']:
            content += '<tr><td>' + str(b[0]) + '</td><td>' + b[1] + '</td><td>' + format8(b[2]) + '</td></tr>'
        content += '</table>'

        content += '</body></html>'
        return bytes(content, 'UTF-8')

    """
    def page_help(self):
        content = '<!DOCTYPE html><html lang="en">\n<head>' \
            + '<meta charset="UTF-8">' \
            + '<title>Particl Stake Pool Help</title></head>' \
            + '<body>' \
            + '<h2>Particl Stake Pool Help</h2>' \
            + '<h3>Help</h3>' \
            + '<p>' \
            + '</p></body></html>'
        return bytes(content, 'UTF-8')
    """

    def putHeaders(self, status_code, content_type):
        self.send_response(status_code)
        if self.server.allow_cors:
            self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-type', content_type)
        self.end_headers()

    def handle_http(self, status_code, path):
        urlSplit = self.path.split('/')
        is_json = False
        try:
            if len(urlSplit) > 1:
                if urlSplit[1] == 'config':
                    self.putHeaders(status_code, 'text/plain')
                    return self.page_config(urlSplit)
                if urlSplit[1] == 'json':
                    is_json = True
                    self.putHeaders(status_code, 'text/plain')
                    if len(urlSplit) > 2:
                        if urlSplit[2] == 'address':
                            return self.js_address(urlSplit)
                        if urlSplit[2] == 'metrics':
                            return self.js_metrics(urlSplit)
                        if urlSplit[2] == 'version':
                            return bytes(json.dumps(self.server.stakePool.getVersions()), 'UTF-8')
                        if urlSplit[2] == 'voting':
                            return bytes(json.dumps(self.server.stakePool.getVotingInfo()), 'UTF-8')
                        if urlSplit[2] == 'pending':
                            return self.js_pending(urlSplit)
                    return self.js_index(urlSplit)
                self.putHeaders(status_code, 'text/html')
                if urlSplit[1] == 'address':
                    return self.page_address(urlSplit)
                if urlSplit[1] == 'version':
                    return self.page_version()
                if urlSplit[1] == 'voting':
                    return self.page_voting_info(urlSplit)
            else:
                self.putHeaders(status_code, 'text/html')
            return self.page_index()
        except IOError as e:
            stake_pool = self.server.stakePool
            if stake_pool.debug:
                stake_pool.log(str(e))
            return self.js_error('IO Error') if is_json else self.page_error('IO Error')
        except Exception as e:
            return self.js_error(str(e)) if is_json else self.page_error(str(e))

    def do_GET(self):
        response = self.handle_http(200, self.path)
        self.wfile.write(response)

    def do_HEAD(self):
        self.putHeaders(200, 'text/html')

    def do_OPTIONS(self):
        self.send_response(200, 'ok')
        if self.server.allow_cors:
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()


class HttpThread(threading.Thread, HTTPServer):
    def __init__(self, fp, hostName, portNo, allow_cors, stakePool, key_salt=None, key_hash=None):
        threading.Thread.__init__(self)

        self.stop_event = threading.Event()
        self.fp = fp
        self.hostName = hostName
        self.portNo = portNo
        self.allow_cors = allow_cors
        self.stakePool = stakePool
        self.management_key_salt = 'ajf8923ol2xcv.' if key_salt is None else key_salt
        self.management_key_hash = 'fd5816650227b75143e60c61b19e113f43f5dcb57e2aa5b6161a50973f2033df' if key_hash is None else key_hash

        self.timeout = 60
        HTTPServer.__init__(self, (self.hostName, self.portNo), HttpHandler)

    def stop(self):
        self.stop_event.set()

        # Send fake request
        conn = http.client.HTTPConnection(self.hostName, self.portNo)
        conn.connect()
        conn.request('GET', '/none')
        response = conn.getresponse()
        data = response.read()
        conn.close()

    def stopped(self):
        return self.stop_event.is_set()

    def serve_forever(self):
        while not self.stopped():
            self.handle_request()
        self.socket.close()

    def run(self):
        self.serve_forever()
