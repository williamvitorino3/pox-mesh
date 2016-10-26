# Copyright 2011 Andreas Wundsam
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

#TODO: Update the datapath to use nicira.py and then delete this file.

import struct

from pox.lib.util import initHelper

# Nicira Vendor extensions. Welcome to embrace-and-extend-town
VENDOR_ID = 0x00002320
# sub_types
"""
Quando o controlador quer mudar o seu papel , que utiliza a mensagem com o seguinte OFPT_ROLE_REQUEST
estrutura (por isso importa o struct. Cada controlador pode enviar uma mensagem OFPT_ROLE_REQUEST para comunicar o seu papel ao switch, 
e o interruptor deve lembrar o papel de cada conexão do controlador . Um controlador pode mudar
papel a qualquer momento , desde que o generation_id na mensagem é atual 
"""
"""
O papel campo é o novo papel que o controlador quer assumir , e pode ter os seguintes valores :
"""
"""
Após o recebimento de uma mensagem OFPT_ROLE_REQUEST , se não há nenhum erro , o interruptor deve retornar
uma mensagem OFPT_ROLE_REPLY . A estrutura desta mensagem é exactamente o mesmo que o
mensagem OFPT_ROLE_REQUEST , eo papel campo é o papel atual do controlador. O campo
generation_id é definido como o generation_id actual ( o generation_id associado com o último sucesso
solicitação de função com OFPCR_ROLE_MASTER papel ou OFPCR_ROLE_SLAVE ), se o generation_id atual
nunca foi definida por um controlador , o campo generation_id na resposta deve ser definida para o campo máximo
valor (o equivalente sem assinatura de -1 ) .
"""
ROLE_REQUEST = 10 
ROLE_REPLY = 11
# role request / reply patterns
ROLE_OTHER = 0
"""
Se o valor papel na mensagem é OFPCR_ROLE_MASTER ou OFPCR_ROLE_SLAVE , o interruptor deve validar
generation_id para verificar as mensagens obsoletos (ver 6.3.6 ) . Se a validação falhar , o interruptor deve descartar
a solicitação de função e retornar uma mensagem de erro Stale
"""
ROLE_MASTER = 1 #Acesso total , no máximo, um mestre.
ROLE_SLAVE = 2 #Acesso somente leitura .

class nx_data(object):
  """ base class for the data field of Nicira vendor extension
      commands. Picked from the floodlight source code.
  """

"""classe base para o campo de dados da extensão do fornecedor Nicira
      comandos . Colhidos a partir do código-fonte do projector .
"""
  def __init__ (self, **kw):
    self.subtype = 0
    self.length = 4

    initHelper(self, kw)

  def _assert (self):
    return (True, None)

"empacotando o pacote"
  def pack (self, assertstruct=True):
    if(assertstruct):
      if(not self._assert()[0]):
        return None
    packed = ""
    packed += struct.pack("!L", self.subtype)
    return packed

"desempacontando o pacote"
  def unpack (self, binaryString):
    if (len(binaryString) < 4):
      return binaryString
    (self.subtype,) = struct.unpack_from("!L", binaryString, 0)
    return binaryString[4:]

  def __len__ (self):
    return 4

    "compara se self e other são iguais"
    "Assim, ao definir  __eq__(), deve-se também definir __ne__()de modo que os operadores irão se comportar conforme o esperado."
  def __eq__ (self, other):
    if type(self) != type(other): return False
    if self.subtype !=  other.subtype: return False
    return True

  def __ne__ (self, other): return not self.__eq__(other)

  def show (self, prefix=''):
    outstr = ''
    outstr += prefix + 'header: \n'
    outstr += prefix + 'subtype: ' + str(self.subtype) + '\n'
    return outstr

class role_data(nx_data):
  """ base class for the data field of nx role requests."""
  "classe base para o campo de solicitações de função nx dados."
  def __init__ (self, subtype, **kw):
    nx_data.__init__(self)
    self.subtype = subtype
    self.role = ROLE_OTHER
    self.length = 8

    initHelper(self, kw)

  def _assert (self):
    return (True, None)

  def pack (self, assertstruct=True):
    if(assertstruct):
      if(not self._assert()[0]):
        return None
    packed = ""
    packed += nx_data.pack(self)
    packed += struct.pack("!L", self.role)
    return packed

  def unpack (self, binaryString):
    if (len(binaryString) < 8):
      return binaryString
    nx_data.unpack(self, binaryString[0:])
    (self.role,) = struct.unpack_from("!L", binaryString, 4)
    return binaryString[8:]

  def __len__ (self):
    return 8

  def __eq__ (self, other):
    if type(self) != type(other): return False
    if not nx_data.__eq__(self, other): return False
    if self.role !=  other.role: return False
    return True

  def __ne__ (self, other): return not self.__eq__(other)

  def show (self, prefix=''):
    outstr = ''
    outstr += prefix + 'header: \n'
    outstr += nx_data.show(self, prefix + '  ')
    outstr += prefix + 'role: ' + str(self.role) + '\n'
    return outstr

class role_request_data(role_data):
  """ Role request. C->S """
  def __init__ (self, **kw):
    role_data.__init__(self, ROLE_REQUEST, **kw)

class role_reply_data(role_data):
  """ Role reply S->C """
  def __init__ (self, **kw):
    role_data.__init__(self, ROLE_REPLY, **kw)

_nx_subtype_to_type = {
    ROLE_REQUEST: role_request_data,
    ROLE_REPLY: role_reply_data
}

def unpack_vendor_data_nx(data):
    if len(data) < 4: raise RuntimeError("NX vendor data<4 bytes")
    nx = nx_data()
    nx.unpack(data)
    if nx.subtype in _nx_subtype_to_type:
      res = _nx_subtype_to_type[nx.subtype]()
      res.unpack(data)
      return res
    else:
      raise NotImplementedError("subtype not implemented: %d" % nx.subtype)
