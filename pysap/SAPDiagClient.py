# pysap - Python library for crafting SAP's network protocols packets
#
# SECUREAUTH LABS. Copyright (C) 2021 SecureAuth Corporation. All rights reserved.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# Author:
#   Martin Gallo (@martingalloar) from SecureAuth's Innovation Labs team.
#

# Standard imports
from random import randint
from socket import error as SocketError
from binascii import unhexlify as unhex
# Custom imports
from pysap.SAPRouter import SAPRoutedStreamSocket
from pysap.SAPDiag import SAPDiag, SAPDiagDP, SAPDiagItem
from pysap.SAPDiagItems import (user_connect_compressed,
                                user_connect_uncompressed,
                                support_data as default_support_data,
                                SAPDiagStep, SAPDiagSupportBits)


class SAPDiagConnection(object):
    """SAP Diag Connection

    This class represents a basic client connection to a Diag server.
    Handles initialization and further interaction by sending/receiving
    packets.
    """

    last_response = None
    """ :ivar: stores the last response received from the server
        :type: :class:`SAPNI<SAPNI.SAPNI>` """

    initialized = False
    """ :ivar: if the connection was initialized
        :type: ``bool`` """

    step = 0
    """ :ivar: number of the last dialog step performed
        :type: ``int`` """

    def __init__(self, host, port, terminal=None, compress=False,
                 init=False, route=None, support_data=default_support_data):
        """Creates the connection to the Diag server.

        :param host: remote host to connect to
        :type host: C{string}

        :param port: remote port to connect to
        :type port: ``int``

        :param terminal: terminal name to use when connecting to the server.
            If no terminal name is specified, a random IP address will be
            generated and used instead of the terminal name.
        :type terminal: C{string}

        :param compress: if true, the compression will be enabled for the
            connection. Otherwise, the connection will be established using
            compression.
        :type compress: ``bool``

        :param init: if true, the initialization will be performed after the
            connection is established.
        :type init: ``bool``

        :param route: route to use for connecting through a SAP Router
        :type route: C{string}

        :param support_data: support data bits to use when initializing. It
            identifies the client's capabilities.
        :type support_data: :class:`SAPDiagItem` or :class:`SAPDiagSupportBits` or C{string}
        """

        self.host = host
        self.port = port
        self.terminal = terminal or self.get_terminal_name()
        self.route = route
        self.support_data = self.get_support_data_item(support_data) or default_support_data
        if compress is True:
            self.compress = 1
        else:
            self.compress = 0
        self._connection = None
        if init:
            self.init()

    def connect(self):
        """Creates a :class:`SAPNIStreamSocket` connection to the host/port. If a route
        was specified, connect to the target Diag server through the SAP Router.
        """
        self._connection = SAPRoutedStreamSocket.get_nisocket(self.host,
                                                              self.port,
                                                              self.route,
                                                              base_cls=SAPDiag)

    @staticmethod
    def get_terminal_name():
        """Generates a random IP address to use as a terminal name. In SAP
        systems that don't implement SAP Note 1497445, the dispatcher registers
        logs the terminal name as provided by the client, or fallback to
        registering the IP address if the terminal name can't be resolved.
        Using a random IP address as terminal name in unpatched systems will
        make the 'terminal' field of the security audit log unreliable.
        """
        return '.'.join(str(randint(0, 255)) for _ in range(4))

    def get_support_data_item(self, support_data):
        if isinstance(support_data, str):
            support_data = SAPDiagSupportBits(unhex(support_data))

        if isinstance(support_data, SAPDiagSupportBits):
            support_data = SAPDiagItem(item_type="APPL",
                                       item_id="ST_USER",
                                       item_sid="SUPPORTDATA",
                                       item_value=support_data)

        if isinstance(support_data, SAPDiagItem):
            return support_data

        return None

    def init(self):
        """Sends an initialization request. If the socket wasn't created,
        call the :class:`connect` method. If compression was specified, the
        initialization will be performed using the respective User
        Connect item.

        :return: initialization response (usually login screen)
        :rtype: :class:`SAPNI<SAPNI.SAPNI>`
        """
        if self._connection is None:
            self.connect()

        # If the connection is compressed, use the respective User Connect item
        if self.compress == 1:
            user_connect = user_connect_compressed
        else:
            user_connect = user_connect_uncompressed

        # The initialization is always performed uncompressed
        self.initialized = True  # XXX: Check that the respose was ok

        return self.sr(SAPDiagDP(terminal=self.terminal) /
                       SAPDiag(compress=0, com_flag_TERM_INI=1) /
                       user_connect / self.support_data)

    def send(self, packet):
        """Sends a packet using the :class:`SAPNIStreamSocket`

        :param packet: packet to send
        :type packet: :class:`SAPDiag<SAPDiag.SAPDiag>`

        """
        if self._connection is not None:
            self._connection.send(packet)

    def receive(self):
        """Receive a :class:`SAPNI<SAPNI.SAPNI>` packet using the :class:`SAPNIStreamSocket`. Response is
        returned and also stored in :class:`last_response`.

        :return: packet received
        :rtype: :class:`SAPNI<SAPNI.SAPNI>`
        """
        if self._connection is not None:
            self.last_response = self._connection.recv()
            return self.last_response
        else:
            return None

    def sr(self, packet):
        """Sends and receive a :class:`SAPNI<SAPNI.SAPNI>` packet using the :class:`SAPNIStreamSocket`

        :param packet: packet to send
        :type packet: :class:`SAPDiag<SAPDiag.SAPDiag>`

        :return: packet received
        :rtype: :class:`SAPNI<SAPNI.SAPNI>`
        """
        if self._connection is not None:
            self.send(packet)
            self.last_response = self.receive()
            return self.last_response
        else:
            return None

    def close(self):
        """Send an 'end of connection' packet and closes the socket

        """
        try:
            self.send(SAPDiag(compress=0, com_flag_TERM_EOC=1))
            self._connection.close()
        except SocketError:  # We don't care about socket errors at this time
            pass

    def sr_message(self, msg):
        """Sends and receive a :class:`SAPDiag<SAPDiag.SAPDiag>` message, prepending the
        Diag header.

        :param msg: items to send
        :type msg: ``list`` of :class:`SAPDiagItem`

        :return: server's response
        :rtype: :class:`SAPNI<SAPNI.SAPNI>`

        """
        return self.sr(SAPDiag(compress=self.compress, message=msg))

    def send_message(self, msg):
        """Sends a :class:`SAPDiag<SAPDiag.SAPDiag>` message, prepending the Diag header.

        :param msg: items to send
        :type msg: ``list`` of :class:`SAPDiagItem`

        """
        self.send(SAPDiag(compress=self.compress, message=msg))

    def interact(self, message):
        """Interacts with the SAP Diag server, adding the :class:`SAPDiagStep` item and
        ending with a 'end of message' item.

        :param message: items to send
        :type message: ``list`` of :class:`SAPDiagItem`

        :return: server's response
        :rtype: :class:`SAPNI<SAPNI.SAPNI>`
        """
        if self.initialized:
            self.step += 1
            message.insert(0, SAPDiagItem(item_type="APPL", item_id="ST_USER",
                                          item_sid=0x26,
                                          item_value=SAPDiagStep(step=self.step)))
            message.append(SAPDiagItem(item_type="EOM"))
            return self.sr_message(message)
        else:
            return None
