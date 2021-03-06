"""Core subscriber utility methods.

Subscriber and number operations are very thin wrappers on the SIPAuthServe
component of openbts-python.  We don't use the openbts lib directly because
it does not natively handle credits, and this allows us to use this module as
the central point of contact for subscriber-related things.

Copyright (c) 2016-present, Facebook, Inc.
All rights reserved.

This source code is licensed under the BSD-style license found in the
LICENSE file in the root directory of this source tree. An additional grant
of patent rights can be found in the PATENTS file in the same directory.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os
import sys

import psycopg2
from osmocom.subscribers import Subscribers

from ccm.common import logger
from core import number_utilities
from core.config_database import ConfigDB
from core.subscriber.base import BaseSubscriber, SubscriberNotFound
from core.exceptions import BSSError


# In our CI system, Postgres credentials are stored in env vars.
PG_USER = os.environ.get('PG_USER', 'endaga')
PG_PASSWORD = os.environ.get('PG_PASSWORD', 'endaga')

class OsmocomSubscriber(BaseSubscriber):

    def __init__(self):
        super(OsmocomSubscriber, self).__init__()
        self.conf = ConfigDB()
        self.subscribers = Subscribers(host=self.conf['bts.osmocom.ip'],
            port=self.conf['bts.osmocom.bsc_vty_port'],
            hlr_loc=self.conf['bts.osmocom.hlr_loc'],
            timeout=self.conf['bss_timeout'])

    def add_subscriber_to_hlr(self, imsi, number, ip, port):
        """Adds a subscriber to the system.

        IP/Port unused in Osmocom implementation.

        """
        try:
            with self.subscribers as s:
                try:
                    # the sub entry should be created on demand
                    # so just check to make sure that it is there
                    s.show('imsi', imsi)
                except ValueError:
                    s.create(imsi)
                s.set_extension(imsi, number)
                s.set_authorized(imsi, 1)
                return s.show('imsi', imsi)
        except Exception as e:
            exc_type, exc_value, exc_trace = sys.exc_info()
            raise BSSError, "%s: %s" % (exc_type, exc_value), exc_trace

    def get_subscribers(self, imsi=''):
        """Get subscriber by imsi."""
        imsi = imsi + "%"
        subscribers = []
        with psycopg2.connect(host='localhost', database='endaga', user=PG_USER,
                password=PG_PASSWORD) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT imsi, balance FROM subscribers WHERE imsi LIKE %s", (imsi,))
                try:
                    with self.subscribers as s:
                        for row in cursor.fetchall():
                            sub_record = s.show('imsi', row[0])
                            if len(sub_record):
                                subscribers.append({
                                    'account_balance': row[1],
                                    'name': row[0], # interface describes name as IMSI
                                    'port': self.get_port(row[0]),
                                    'ipaddr': self.get_ip(row[0]),
                                    'caller_id': sub_record['extension'],
                                    'numbers': [sub_record['extension']]})
                except Exception as e:
                    exc_type, exc_value, exc_trace = sys.exc_info()
                    raise BSSError, "%s: %s" % (exc_type, exc_value), exc_trace
        return subscribers

    def add_number(self, imsi, number):
        """Associate another number with an IMSI.

           Raises:
              SubscriberNotFound if imsi is not found
        """
        raise NotImplementedError('only one number per imsi')

    def delete_number(self, imsi, number):
        """Disassociate a number with an IMSI.

           Raises:
              SubscriberNotFound if imsi is not found
              ValueError if number doesn't belong to IMSI
                  or this is the sub's last number
        """
        raise NotImplementedError('cannot delete the only number associated with this account')

    def get_caller_id(self, imsi):
        """Get a subscriber's caller_id.

           Raises:
              SubscriberNotFound if imsi is not found
        """
        try:
            with self.subscribers as s:
                try:
                    return s.show('imsi', imsi)['extension']
                except ValueError as e:
                    raise SubscriberNotFound(imsi)
        except Exception as e:
            exc_type, exc_value, exc_trace = sys.exc_info()
            raise BSSError, "%s: %s" % (exc_type, exc_value), exc_trace

    def get_ip(self, imsi):
        """Get a subscriber's IP address.
        """
        return self.conf['bts.osmocom.ip']

    def get_port(self, imsi):
        """Get a subscriber's port.
        """
        return self.conf['bts.osmocom.sip_port']

    def delete_subscriber_from_hlr(self, imsi):
        """Removes a subscriber from the system.

           Raises:
              SubscriberNotFound if imsi is not found
        """
        try:
            with self.subscribers as s:
                try:
                    return s.delete(imsi)
                except ValueError as e:
                    raise SubscriberNotFound(imsi)
        except Exception as e:
            exc_type, exc_value, exc_trace = sys.exc_info()
            raise BSSError, "%s: %s" % (exc_type, exc_value), exc_trace

    def get_numbers_from_imsi(self, imsi):
        """Gets numbers associated with a subscriber.

           Raises:
              SubscriberNotFound if imsi is not found
        """
        try:
            with self.subscribers as s:
                try:
                    return [s.show('imsi', imsi)['extension']]
                except ValueError as e:
                    raise SubscriberNotFound(imsi)
        except Exception as e:
            exc_type, exc_value, exc_trace = sys.exc_info()
            raise BSSError, "%s: %s" % (exc_type, exc_value), exc_trace

    def get_imsi_from_number(self, number, canonicalize=True):
        """Gets the IMSI associated with a number.

           Raises:
              SubscriberNotFound if imsi is not found
        """
        if canonicalize:
            number = number_utilities.canonicalize(number)
        try:
            with self.subscribers as s:
                try:
                    return 'IMSI' + s.show('extension', number)['imsi']
                except ValueError as e:
                    raise SubscriberNotFound('MSISDN %s' % number)
        except Exception as e:
            exc_type, exc_value, exc_trace = sys.exc_info()
            raise BSSError, "%s: %s" % (exc_type, exc_value), exc_trace

    def get_username_from_imsi(self, imsi):
        """Gets the SIP name of the subscriber

           Raises:
              SubscriberNotFound if imsi is not found
        """
        return self.get_caller_id(imsi)

    def get_imsi_from_username(self, username):
        """Get the IMSI from the SIP name.

           This doesn't raise exceptions because it cannot fail or the dialplan
           chatplan will fail

           XXX: in osmocom, the subscribers are still in the HLR even if they
           are not provisioned
        """
        return self.get_imsi_from_number(username, canonicalize=False)

    def is_authed(self, imsi):
        """Returns True if the subscriber is provisioned and authorized
        to use GSM services. The subscriber is provisioned if a record
        exists in the postgres table, and the subscriber is authorized
        if authorized=1 in the osmocom HLR.
        """

        provisioned = len(self.get_subscriber_states(imsis=[imsi])) > 0
        if not provisioned:
            return False

        try:
            with self.subscribers as s:
                try:
                    return s.show('imsi', imsi)['authorized'] == '1'
                except ValueError:
                    return False
        except Exception as e:
            exc_type, exc_value, exc_trace = sys.exc_info()
            raise BSSError, "%s: %s" % (exc_type, exc_value), exc_trace

    def get_gprs_usage(self, target_imsi=None):
        """Get all available GPRS data, or that of a specific IMSI (experimental).

        Will return a dict of the form: {
          'ipaddr': '192.168.99.1',
          'downloaded_bytes': 200,
          'uploaded_bytes': 100,
        }

        Or, if no IMSI is specified, multiple dicts like the one above will be
        returned as part of a larger dict, keyed by IMSI.

        Args:
          target_imsi: the subsciber-of-interest
        """
        raise NotImplementedError()
