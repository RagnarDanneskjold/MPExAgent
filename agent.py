# -*- coding: utf-8 -*-
#@+leo-ver=5-thin
#@+node:jurov.20121005183137.2119: * @file /home/juro/work/coinbr/mpexagent/MPExAgent/agent.py
#@@first
#@@language python
#@@tabwidth -4
#@+others
#@+node:jurov.20121005183137.2120: ** mpexagent declarations
import logging

from twisted.python import log as twlog

if __name__ == '__main__':
    logging.basicConfig(filename='mpexagent.log',level=logging.DEBUG,format='%(asctime)s [%(name)s]:%(levelname)s:%(message)s')
    observer = twlog.PythonLoggingObserver()
    observer.start()

log = logging.getLogger(__name__)

from mpex import MPEx
from pyparse import parseStat,parseDeposit,parseOrder,parseExercise
from getpass import getpass
from twisted.internet import reactor
#, ssl
from twisted.web import server
import traceback

from jsonrpc.server import ServerEvents, JSON_RPC
from pprint import pformat

from decimal import Decimal

SATOSHI=Decimal(100000000)
#@+node:jurov.20121005183137.2121: ** processStat
def processStat(string):
    """Parses STAT response into in following structure, adapted to easy conversion to JSON:
    { 'timestamp': '2012-04-22T22:42:25', # all dates in isoformat() 
        'unixTimeStamp': 1335127345, #TODO STAT looks like it provides fractions of second too
        'current_holdings': {'CxBTC': 1438734341, #all btc amounts are converted to satoshi
                      'O.BTCUSD.P060T': 10,
                      #..etc..
                      },
        'dividends': [{'amount': 73116162, # whole part may be missing if no dividends in STAT
                'date': '2012-06-30T01:11:55+00:00',
                'mpsic': 'S.MPOE'},
                #..etc..
                ],
        'orders': {'113634': {'amount': 100000, # whole part may be missing if no active orders in STAT
                       'buysell': 'B',
                       'mpsic': 'S.MPOE',
                       'unitprice': 4000},
            '49901': {'amount': 100000, #keys are MPEx order IDs
                      'buysell': 'S',
                      'mpsic': 'O.BTCUSD.C110T',
                      'unitprice': 123456},
                      #..etc..
                      },
        'transactions': [{'amount': 10, # whole part may be missing if no transactions in STAT
                   'buysell': 'B',
                   'date': '2012-04-22T20:41:22+00:00',
                   'mpsic': 'S.MPOE',
                   'total': 2338970,
                   'unitprice': 233897},
                  {'amount': 1,
                   'buysell': 'S',
                   'date': '2012-07-28T17:28:42+00:00',
                   'mpsic': 'O.BTCUSD.C110T',
                   'total': 5110408,
                   'unitprice': 5120650},
                   #...etc..
                   ]
        #TODO option contracts
        }"""    
    data = parseStat(string)
    #TODO parse exception?
    #get rid of decimals
    if 'unixTimeStamp' in data:
        holds = data['current_holdings']
        for item in holds:
            if item == 'CxBTC':
                holds[item] = int(SATOSHI*holds[item])
            else:
                holds[item] =  int(holds[item])
    if 'unixTimeStamp' in data:
        data['unixTimeStamp'] = int(data['unixTimeStamp'])
    if 'timestamp' in data:
        data['timestamp'] = data['timestamp'].isoformat()
        
    if 'orders' in data:
        orders = data['orders']
        for orderid in orders:
            orders[orderid]['unitprice'] = int(orders[orderid]['unitprice']*SATOSHI)
            orders[orderid]['amount'] = int(orders[orderid]['amount'])
            
    if 'transactions' in data:
        txs = data['transactions']
        for tx in txs:
            tx['total'] = int(tx['total']*SATOSHI)
            tx['unitprice'] = int(tx['unitprice']*SATOSHI)
            tx['amount'] = int(tx['amount'])
            #sorry, no JSON support for dates
            tx['date'] = tx['date'].isoformat()
        
    if 'dividends' in data:
        divs = data['dividends']
        for div in divs:
            div['amount'] = int(div['amount'] * SATOSHI)
            div['date'] = div['date'].isoformat()
            
    return data    
#@+node:jurov.20121005183137.2122: ** processNewOrder
def processNewOrder(string):
    """Parses response to BUY/SELL command and returns dict in format:
    {'amount': 1, 'buysell': 'B', 'unitprice': 20000000, 'mpsic': 'O.BTCUSD.C110T'}"""
    data = parseOrder(string)
    if 'unitprice' in data:
        data['unitprice'] = int(SATOSHI*data['unitprice'])
    if 'amount' in data:
        data['amount'] = int(data['amount'])
    if 'expiry' in data:
        data['expiry'] = data['expiry'].isoformat()
    return data
#@+node:jurov.20121005183137.2123: ** processDeposit
def processDeposit(string):
    """Parses response to DEPOSIT command and returns dict in format: {'amount': 1003925374, 'address': '1Fx3N5iFPDQxUKhhmDJqCMmi3U8Y7gSncx'}"""
    data = parseDeposit(string)
    #TODO parse exception?
    if'amount' in data:
        data['amount'] = int(data['amount'] * SATOSHI)
    return data
#@+node:jurov.20121005183137.2124: ** processExercise
def processExercise(string):
    """Parses response to EXERCISE command and returns dict in format:
        {'amount': 1, 'total': 177075099, 'mpsic': 'O.BTCUSD.C120T'}
        """
    data = parseExercise(string)
    #TODO parse exception?
    if'total' in data:
        data['total'] = int(data['total'] * SATOSHI)
    return data
#@+node:jurov.20121005183137.2125: ** class MPExAgent
class MPExAgent(MPEx):
    #@+others
    #@+node:jurov.20121005183137.2126: *3* neworder
    def neworder(self,orderType,mpsic,amount,price = None):
        """ Place new order.
        orderType : 'B' or 'S'
        mpsic
        amount
        price - unit price in satoshi
       Deferred result is dict in format: 
     {'message': decrypted MPEx reply incl. PGP signature, 
     'data': result of processNewOrder() if order was successful. It is good to check this, because if your btc/item balance is not sufficient but you still have some balance, MPEx still accepts and modifies the order.
     'result': 'OK' if placing order was successful;
     'Failed': if order was syntactically correct, but failed due to business reason (no balance at all)
      'Error' otherwise}      
        """
        #TODO check whether arguments are numeric
        cmd = None
        if(orderType == 'B'):
            cmd = 'BUY|'
        if(orderType == 'S'):
            cmd = 'SELL|'
        cmd += mpsic + '|' + str(amount)
        if price and price > 0:
            cmd += '|'+ str(price)
        #log.debug('neworder:' + pformat(cmd))
        #@+<<neworderCb>>
        #@+node:jurov.20121005183137.2127: *4* <<neworderCb>>
        def neworderCb(reply):
            if "You don't hold enough assets" in reply:
                log.error('Placing order %s failed with reply: %s',cmd,reply)
                return {'result':'Failed', 'message':reply}
            if 'has been received and will be processed.' in reply:
                data = processNewOrder(reply)
                log.debug('Placing order %s success',cmd)
                #When selling more than balance or buying more than BTC balance, the order amount is automatically adjusted and must be checked!
                return {'result':'OK', 'order':data, 'message':reply}
            log.error('placing order %s got unexpected reply:%s',cmd, reply)
            return {'result':'Error', 'message':reply}

        #@-<<neworderCb>>
        d = MPEx.command(self,cmd)
        d.addCallback(neworderCb)
        return d
    #@+node:jurov.20121005183137.2128: *3* stat
    def stat(self):
        """
        No parameters. 
        
        Deferred result is either dict - result of processStat() if parsing STAT request was successful, 
     or simple False value.}        
        """
        #@+<<statCb>>
        #@+node:jurov.20121005183137.2129: *4* <<statCb>>
        def statCb(reply):
            if reply is None:
                log.error('STAT failed')
                return False
            return processStat(reply)
            
        #@-<<statCb>>
        d = self.command('STAT')
        d.addCallback(statCb)
        return d
    #@+node:jurov.20121005183137.2130: *3* cancel
    def cancel(self,orderid):
        """Cancel order with given mpex id. Using strings for orderid is preferred.
        Deferred result is dict in format:
     {'message': decrypted MPEx reply incl. PGP signature, 
     'result': 'OK' if cancel request was successful;
        'Failed' if the reply was Mangled CANCEL order. If you are sure the cancel request is correct, call STAT to check the situation (order could have been already executed) and retry later;
        'Retry' if the reply was Order ... can not be cancelled at this time. Same as above 'Failed' case applies, this seems to happen mostly in case the order is very young;
        'Error' otherwise}        
        """
        cmd = 'CANCEL|%s' % orderid
        #@+<<cancelCb>>
        #@+node:jurov.20121005183137.2131: *4* <<cancelCb>>
        def cancelCb(reply):
            if 'Mangled CANCEL order.' in reply:
                log.error('Canceling order %s error: %s', orderid,  reply)
                #send 'Failed' instead of Error because the cancel may be
                #actually valid, only the order was filled recently
                return {'result':'Failed', 'message' : reply}
            if 'has been canceled' in reply:
                log.debug('Canceling order %s success', orderid)
                return {'result':'OK', 'message' : reply}
            if 'can not be cancelled at this time' in reply:
                log.info('Canceling order %s should be retried later',orderid)
                return {'result':'Retry', 'message' : reply}
                
            log.error('Canceling order %s got unexpected reply: %s', orderid, reply)
            return {'result' :'Error', 'message' : reply}
            
        #@-<<cancelCb>>
        d = self.command(cmd)
        d.addCallback(cancelCb)
        return d
    #@+node:jurov.20121005183137.2132: *3* deposit
    def deposit(self,amount):
        """Sends deposit command to MPEx. Parameters:
            amount : deposited amount
        Deferred result is dict in format:
     {'message': decrypted MPEx reply incl. PGP signature, 
     'data': result of processDeposit() if deposit request was successful, 
     'result': 'OK' if deposit request was successful, 'Error' otherwise}        
        """
        cmd = 'DEPOSIT|%d' % amount
        #@+<<depositCb>>
        #@+node:jurov.20121005183137.2133: *4* <<depositCb>>
        def depositCb(reply):
            if 'In order to make this deposit' in reply:
                data = processDeposit(reply)
                return {'result':'OK', 'data':data, 'message':reply}

            log.error('%s got unexpected reply: %s', cmd, reply)
            return {'result' :'Error', 'message' : reply}
        #@-<<depositCb>>
        d = self.command(cmd)
        d.addCallback(depositCb)
        return d
    #@+node:jurov.20121005183137.2134: *3* withdraw
    def withdraw(self,amount,address):
        return False
    #@+node:jurov.20121005183137.2135: *3* exercise
    def exercise(self,mpsic,amount):
        """Sends exercise command to MPEx. Deferred result is dict in format:
     {'message': decrypted MPEx reply incl. PGP signature, 
     'data': result of processExercise() if exercise was successful, 
     'result': 'OK' if exercise was successful, 'Error' otherwise}        
        """
        cmd = 'EXERCISE|%s|%d' % (mpsic,amount)
        #@+<<exerciseCb>>
        #@+node:jurov.20121005183137.2136: *4* <<exerciseCb>>
        def exerciseCb(reply):
            if('has been received and will be executed') in reply:
                data = processExercise(reply)
                return {'result':'OK', 'data':data, 'message':reply}
                
            log.error('%s got unexpected reply: %s', cmd, reply)
            return {'result' :'Error', 'message' : reply}
        #@-<<exerciseCb>>
        d = self.command(cmd)
        d.addCallback(exerciseCb)
        return d
    #@+node:jurov.20121005183137.2137: *3* echo
    def echo(self,value):
        return "OK " + value
    #@+node:jurov.20121005183137.2138: *3* exception
    def exception(self,value):
        raise ValueError("Test exception, data: %s" % value)
    #@-others
#@+node:jurov.20121005183137.2139: ** class RPCServer
class RPCServer(ServerEvents):
    methods = set(['neworder','stat','cancel','deposit','withdraw','exercise','echo'])
    agent = None
    #@+others
    #@+node:jurov.20121005183137.2140: *3* log
    def log(self, responses, txrequest, error):
        log.debug("txrequest code: %s",txrequest.code)
        if isinstance(responses, list):
            for response in responses:
                msg = self._get_msg(response)
                log.debug("txrequest:%s %s",txrequest, msg)
        else:
            msg = self._get_msg(responses)
            log.debug("txrequest:%s %s",txrequest, msg)
    #@+node:jurov.20121005183137.2141: *3* findmethod
    def findmethod(self, method, args=None, kwargs=None):
        if self.agent and method in self.methods:
            return getattr(self.agent, method)
        else:
            return None
    #@+node:jurov.20121005183137.2142: *3* _get_msg
    def _get_msg(self, response):
        log.debug('response: %s', repr(response))
        if hasattr(response,'id'):
            return ' '.join(str(x) for x in [response.id, response.result or response.error])
        else: 
            #if isinstance(response,Exception):
            return str(response)
            
    #@+node:jurov.20121005183137.2143: *3* defer
    def defer(self, method, *a, **kw):
        d = method(*a,**kw)  
        if hasattr(d,'addErrback'):  
            d.addErrback(log.error)
        return d
    #@-others
#@+node:jurov.20121005183137.2144: ** main
def main():
    try:
        mpexagent = MPExAgent()
        mpexagent.passphrase = getpass("Enter your GPG passphrase: ")
        root = JSON_RPC().customize(RPCServer)
        root.eventhandler.agent = mpexagent
        site = server.Site(root)    
        
        # 8007 is the port you want to run under. Choose something >1024
        PORT = 8007
        log.info('Listening on port %d...', PORT)
        reactor.listenTCP(PORT, site)
        reactor.run()
    except KeyboardInterrupt:
        print '^C received, shutting down server'
        server.socket.close()
#@-others

if __name__ == '__main__':
    main()

#@-leo