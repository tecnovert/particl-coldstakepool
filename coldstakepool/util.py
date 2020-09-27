# -*- coding: utf-8 -*-

# Copyright (c) 2018-2020 The Particl Core developers
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

import time
import json
import urllib
import decimal
import hashlib
import traceback
import threading
from xmlrpc.client import (
    Transport,
    Fault,
)
from .contrib.segwit_addr import bech32_decode, convertbits, bech32_encode


WRITE_TO_LOG_FILE = True
COIN = 100000000
DCOIN = decimal.Decimal(COIN)
mxLog = threading.Lock()


def logm(fp, s, tag='', printstd=True, writetofile=WRITE_TO_LOG_FILE):
    mxLog.acquire()
    try:
        if printstd:
            print(s)

        if writetofile:
            fp.write(tag + s + '\n')
            fp.flush()
    finally:
        mxLog.release()


def logmt(fp, s, printstd=True, writetofile=WRITE_TO_LOG_FILE):
    logm(fp, time.strftime('%y-%m-%d_%H-%M-%S', time.localtime()) + '\t' + s, printstd=printstd, writetofile=writetofile)


def makeInt(v):
    return int(dquantize(decimal.Decimal(v) * DCOIN).quantize(decimal.Decimal(1)))


def format8(i):
    n = abs(i)
    quotient = n // COIN
    remainder = n % COIN
    rv = "%d.%08d" % (quotient, remainder)
    if i < 0:
        rv = '-' + rv
    return rv


def format16(i):
    n = abs(i)
    quotient = n // (COIN * COIN)
    remainder = n % (COIN * COIN)
    rv = "%d.%016d" % (quotient, remainder)
    if i < 0:
        rv = '-' + rv
    return rv


def toBool(s):
    return s.lower() in ["1", "true"]


def dquantize(n, places=8):
    return n.quantize(decimal.Decimal(10) ** -places)


def jsonDecimal(obj):
    if isinstance(obj, decimal.Decimal):
        return str(obj)
    raise TypeError


def dumpj(jin, indent=4):
    return json.dumps(jin, indent=indent, default=jsonDecimal)


def dumpje(jin):
    return json.dumps(jin, default=jsonDecimal).replace('"', '\\"')


__b58chars = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def b58decode(v, length=None):
    long_value = 0
    for (i, c) in enumerate(v[::-1]):
        ofs = __b58chars.find(c)
        if ofs < 0:
            return None
        long_value += ofs * (58**i)
    result = bytes()
    while long_value >= 256:
        div, mod = divmod(long_value, 256)
        result = bytes((mod,)) + result
        long_value = div
    result = bytes((long_value,)) + result
    nPad = 0
    for c in v:
        if c == __b58chars[0]:
            nPad += 1
        else:
            break
    pad = bytes((0,)) * nPad
    result = pad + result
    if length is not None and len(result) != length:
        return None
    return result


def b58encode(v):
    long_value = 0
    for (i, c) in enumerate(v[::-1]):
        long_value += (256**i) * c

    result = ''
    while long_value >= 58:
        div, mod = divmod(long_value, 58)
        result = __b58chars[mod] + result
        long_value = div
    result = __b58chars[long_value] + result

    # leading 0-bytes in the input become leading-1s
    nPad = 0
    for c in v:
        if c == 0:
            nPad += 1
        else:
            break
    return (__b58chars[0] * nPad) + result


def bech32Decode(hrp, addr):
    hrpgot, data = bech32_decode(addr)
    if hrpgot != hrp:
        return None
    decoded = convertbits(data, 5, 8, False)
    if decoded is None or len(decoded) < 2 or len(decoded) > 40:
        return None
    return bytes(decoded)


def bech32Encode(hrp, data):
    ret = bech32_encode(hrp, convertbits(data, 8, 5))
    if bech32Decode(hrp, ret) is None:
        return None
    return ret


def decodeAddress(address_str):
    b58_addr = b58decode(address_str)
    if b58_addr is not None:
        return b58_addr[:-4]
    return None


def encodeAddress(address):
    checksum = hashlib.sha256(hashlib.sha256(address).digest()).digest()
    return b58encode(address + checksum[0:4])


class Jsonrpc():
    # __getattr__ complicates extending ServerProxy
    def __init__(self, uri, transport=None, encoding=None, verbose=False,
                 allow_none=False, use_datetime=False, use_builtin_types=False,
                 *, context=None):
        # establish a "logical" server connection

        # get the url
        parsed = urllib.parse.urlparse(uri)
        if parsed.scheme not in ("http", "https"):
            raise OSError("unsupported XML-RPC protocol")
        self.__host = parsed.netloc
        self.__handler = parsed.path
        if not self.__handler:
            self.__handler = "/RPC2"

        if transport is None:
            handler = Transport
            extra_kwargs = {}
            transport = handler(use_datetime=use_datetime,
                                use_builtin_types=use_builtin_types,
                                **extra_kwargs)
        self.__transport = transport

        self.__encoding = encoding or 'utf-8'
        self.__verbose = verbose
        self.__allow_none = allow_none

    def close(self):
        if self.__transport is not None:
            self.__transport.close()

    def json_request(self, method, params):
        try:
            connection = self.__transport.make_connection(self.__host)
            headers = self.__transport._extra_headers[:]

            request_body = {
                'method': method,
                'params': params,
                'id': 2
            }

            connection.putrequest("POST", self.__handler)
            headers.append(("Content-Type", "application/json"))
            headers.append(("User-Agent", 'jsonrpc'))
            self.__transport.send_headers(connection, headers)
            self.__transport.send_content(connection, json.dumps(request_body, default=jsonDecimal).encode('utf-8'))

            resp = connection.getresponse()
            return resp.read()

        except Fault:
            raise
        except Exception:
            # All unexpected errors leave connection in
            # a strange state, so we clear it.
            self.__transport.close()
            raise

        """
        #We got an error response.
        #Discard any response data and raise exception
        if resp.getheader("content-length", ""):
            resp.read()
        raise ProtocolError(
            self.__host + self.__handler,
            resp.status, resp.reason,
            dict(resp.getheaders())
            )
        """


def callrpc(rpc_port, auth, method, params=[], wallet=None, rpc_host='127.0.0.1'):
    try:
        url = 'http://{}@{}:{}/'.format(auth, rpc_host, rpc_port)
        if wallet is not None:
            url += 'wallet/' + urllib.parse.quote(wallet)
        x = Jsonrpc(url)

        v = x.json_request(method, params)
        x.close()
        r = json.loads(v.decode('utf-8'))
    except Exception as e:
        traceback.print_exc()
        raise ValueError('RPC Server Error')

    if 'error' in r and r['error'] is not None:
        raise ValueError('RPC error ' + str(r['error']))

    return r['result']


def make_rpc_func(rpc_host, rpc_port, rpc_auth):
    rpc_host = rpc_host
    rpc_port = rpc_port
    rpc_auth = rpc_auth

    def rpc_func(method, params=None, wallet=None):
        nonlocal rpc_host, rpc_port, rpc_auth
        return callrpc(rpc_port, rpc_auth, method, params, wallet, rpc_host=rpc_host)
    return rpc_func
