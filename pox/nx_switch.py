# -*- coding: utf-8 -*-
# Copyright 2011,2012 Andreas Wundsam
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import inspect

import pox.openflow.libopenflow_01 as of
import pox.openflow.nicira_ext as nx
from pox.datapaths.switch import SoftwareSwitch, OFConnection

_slave_blacklist = set([of.ofp_flow_mod, of.ofp_packet_out, of.ofp_port_mod,
                        of.ofp_barrier_request])
_messages_for_all = set([of.ofp_port_status])


class NXSoftwareSwitch (SoftwareSwitch):
  """
  Software datapath with Nicira (NX) extensions

  Extension of the software switch that supports some of the Nicira (NX) vendor
  extensions that are part of Open vSwitch.

  In particular, this include the ability for a switch to connect to multiple
  controllers at the same time.

  In the beginning, all controllers start out as equals (ROLE_OTHER). Through
  the NX vendor message role_request, one controller can be promoted to
  ROLE_MASTER, in which case all other controllers are downgraded to slave
  status.

  The switch doesn't accept state-mutating messages (e.g., FLOW_MOD, see
  _slave_blacklist) from slave controllers.

  Messages are distributed to controllers according to their type:
    - symmetric message replies are sent to the controller that initiated them
      (e.g., STATS_REQUEST -> REPLY)
    - port_status messages are distributed to all controllers
    - all other messages are distributed to the master controller, or if none
      is present, any controller in ROLE_OTHER
  -----------------------------------------------------------------------------
  Pacote de dados de software com extensões Nicira (NX)

  Extensão do switch de software que suporta alguns dos fornecedores Nicira (NX)
  Extensões que fazem parte do Open vSwitch.

  Em particular, isso inclui a capacidade de um switch se conectar a múltiplos
  Controladores ao mesmo tempo.

  No início, todos os controladores começam como iguais (ROLE_OTHER). Através
  A mensagem do fornecedor NX role_request, um controlador pode ser promovido para
  ROLE_MASTER, caso em que todos os outros controladores são desclassificados para slave
  Status.

  O comutador não aceita mensagens de mutação de estado (por exemplo, FLOW_MOD, consulte
  _slave_blacklist) dos controladores escravos.

  As mensagens são distribuídas aos controladores de acordo com seu tipo:
    - as respostas de mensagem simétricas são enviadas ao controlador que as iniciou
      (Por exemplo, STATS_REQUEST -> REPLY)
    - as mensagens port_status são distribuídas para todos os controladores
    - todas as outras mensagens são distribuídas para o controlador mestre, ou
      Está presente, qualquer controlador em ROLE_OTHER
  """
  
  def __init__ (self, *args, **kw):
    #"Inicialização"
    SoftwareSwitch.__init__(self, *args, **kw)
    self.role_by_conn={}
    self.connections = []
    self.connection_in_action = None
    # index of the next 'other' controller to get a message
    # (for round robin of async messages)
    #-----------------------------------------------------
    #Índice do próximo 'outro' controlador para obter uma mensagem
     #(Para round robin de mensagens assíncronas)
    self.next_other = 0

    # Set of connections to which we have sent hellos.  This is used to
    # as part of overriding the single-connection logic in the superclass.
    #-----------------------------------------------------
    #Conjunto de conexões para o qual enviamos hellos. Isso é usado 
    # Como parte da substituição da lógica de conexão única na superclasse.
    self._sent_hellos = set()

  def rx_message (self, connection, msg):
    """
    Handles incoming messages
    ---------------------------------
    Tratamento de mensagens recebidas

    @overrides SoftwareSwitch.rx_message
    Overrides: Redefinição (Polimorfismo)
    """

    #"verifica se a conexão não é permitida"
    self.connection_in_action = connection
    if not self.check_rights(msg, connection):
      self.log.warn("Message %s not allowed for slave controller %d", msg,
                    connection.ID)
      self.send_vendor_error(connection)
    else:
      SoftwareSwitch.rx_message(self, connection, msg)

    self.connection_in_action = None

  
  def check_rights (self, ofp, connection):
    #"Checa os direitos"
    if self.role_by_conn[connection.ID] != nx.ROLE_SLAVE:
      return True
    else:
      return not type(ofp) in _slave_blacklist

  
  """
  OFPET_BAD_REQUEST: Se um dispositivo OpenFlow recebe outra mensagem em um dispositivo auxiliar não confiável
  Conexão antes de receber uma mensagem Hello, o dispositivo deve assumir que a conexão está configurada
  Corretamente e usar o número da versão dessa mensagem, ou ele deve retornar uma mensagem de erro com
  OFPET_BAD_REQUEST tipo e OFPBRC_BAD_VERSION código.
  """
  def send_vendor_error (self, connection):
    err = of.ofp_error(type=of.OFPET_BAD_REQUEST, code=of.OFPBRC_BAD_VENDOR)
    connection.send(err)
    #"Define o caso de envio do vendor "
    #"OFPBRC_BAD_VENDOR: Um controlador pode solicitar que sua função seja alterada para OFPCR_ROLE_SLAVE. Nesta função, o controlador"
    #"Tem acesso somente leitura para o switch."
  
  def send (self, message):
    #"Envio de mesagem: procura a conexão para enviar a mensagem"
    connections_used = []
    if type(message) in _messages_for_all:
      for c in self.connections:
        c.send(message)
        connections_used.append(c)
    elif self.connection_in_action:
      #self.log.info("Sending %s to active connection %d",
      #              (str(message), self.connection_in_action.ID))
      self.connection_in_action.send(message)
      connections_used.append(self.connection_in_action)
    else:
      masters = [c for c in self.connections
                 if self.role_by_conn[c.ID] == nx.ROLE_MASTER]
      if len(masters) > 0:
        masters[0].send(message)
        connections_used.append(masters[0])
      else:
        others = [c for c in self.connections
                  if self.role_by_conn[c.ID] == nx.ROLE_OTHER]
        if len(others) > 0:
          self.next_other = self.next_other % len(others)
          #self.log.info("Sending %s to 'other' connection %d",
          #              (str(message), self.next_other))
          others[self.next_other].send(message)
          connections_used.append(others[self.next_other])
          self.next_other += 1
        else:
          self.log.info("Could not find any connection to send messages %s",
                        str(message))
    return connections_used

  
  def add_connection (self, connection):
    #"Adiciona a conexão"
    self.role_by_conn[connection.ID] = nx.ROLE_OTHER
    connection.set_message_handler(self.rx_message)
    self.connections.append(connection)
    return connection

  
  def set_connection (self, connection):
    #"Estabelece a conexão"
    self.add_connection(connection)

  
  def set_role (self, connection, role):
   #"Estabelece funções:  A função de campo é a nova função que o controlador deseja assumir e pode ter os seguintes valores"
   #"ROLE_MASTER: Acesso total, no máximo um mestre"
   #"ROLE_SLAVE: Acesso somente leitura"
   self.role_by_conn[connection.ID] = role
    if role == nx.ROLE_MASTER:
      for c in self.connections:
        if c != connection:
          self.role_by_conn[c.ID] = nx.ROLE_SLAVE

  
  def _rx_hello (self, ofp, connection):
    #"Substituir a lógica usual hello-send"
    #"Se a conexão não é _sent_hellos, add conexão"
    # Override the usual hello-send logic
    if connection not in self._sent_hellos:
      self._sent_hellos.add(connection)
      self.send_hello(force=True)

  
  def _rx_vendor (self, vendor, connection):
    #"rx_vendor: Agora, os fornecedores podem adicionar suas próprias extensões, embora ainda estejam em conformidade com o OpenFlow. "
    #"A primeira maneira de fazer isso é com o novo tipo de mensagem OFPT_VENDOR"
    self.log.debug("Vendor %s %s", self.name, str(vendor))
    if vendor.vendor == nx.VENDOR_ID:
      try:
        data = nx.unpack_vendor_data_nx(vendor.data)
        if isinstance(data, nx.role_request_data):
          self.set_role(connection, data.role)
          reply = of.ofp_vendor(xid=vendor.xid, vendor = nx.VENDOR_ID,
                                data = nx.role_reply_data(role = data.role))
          self.send(reply)
          return
      except NotImplementedError:
        self.send_vendor_error(connection)
    else:
      return SoftwareSwitch._rx_vendor(self, vendor)
