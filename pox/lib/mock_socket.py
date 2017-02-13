"""
Este módulo fornece um MockSocket que pode ser usado para conexões TCP falsas dentro do simulador.

This module provides a MockSocket that can be used to fake TCP connections inside of the simulator
"""

class MockSocket:
  """
      Um Mock simulado que funciona em um canal de envio e um de mensagem de recebimento.
      Use MockSocket.pair () para obter um par de MockSockets conectados

      A mock socket that works on a sending and a receiving message channel. Use
      MockSocket.pair() to get a pair of connected MockSockets

      TODO: model failure modes
  """
  def __init__(self, receiving, sending):
    self.receiving = receiving
    self.sending = sending

  def send(self, data):
    """
    Envia dados de saída..
    :param data: Dados a serem enviados.
    :return: Objeto de envio.
    """
    """ Send data out on this socket. Data will be available for reading at the receiving
        socket pair. Note that this currently always succeeds and never blocks (unlimited
        receive buffer size)
    """
    return self.sending.send(data)

  def recv(self, max_size=None):
    """
    Recebe informações do socket.
    :param max_size: Tamanho máximo do buffer.
    :return: Dados recebidos.
    """
    """ receive data on this sockect. If no data is available to be received, return "".
        NOTE that this is non-standard socket behavior and should be changed to mimic either
        blocking on non-blocking socket semantics
    """
    return self.receiving.recv(max_size)

  def set_on_ready_to_recv(self, on_ready):
    """
    Manipula on_ready (socket, size) para ser chamado quando os dados estão disponíveis
    para leitura neste soquete
    :param on_ready: Método à ser chamado.
    :return: Sem retorno.
    """
    """ set a handler function on_ready(socket, size) to be called when data is available
    for reading at this socket """
    self.receiving.on_data = lambda channel, size: on_ready(self, size)

  def ready_to_recv(self):
    """
    Verifica se o socket está pronto para receber dados.
    :return: Booleano.
    """
    return not self.receiving.is_empty()

  def ready_to_send(self):
    """
    Verifica se o socket está pronto para enviar dados.
    :return: Booleano.
    """
    return self.sending.is_full()

  def shutdown(self, sig=None):
    """
    Desliga o socket.
    :param sig: Argumento não utilizado.
    :return: Sem retorno.
    """
    """ shutdown a socket. Currently a no-op on this MockSocket object.
        TODO: implement more realistic closing semantics
    """
    pass

  def close(self):
    """
    Fecha o socket.
    :return: Sem retorno.
    """
    """ close a socket. Currently a no-op on this MockSocket object.
        TODO: implement more realistic closing semantics
    """
    pass

  def fileno(self):
    """
    Pega o pseudo-fileno deste Mock Socket
    :return: Retornar o pseudo-fileno deste Mock Socket.
    """
    """ return the pseudo-fileno of this Mock Socket. Currently always returns -1.
        TODO: assign unique pseudo-filenos to mock sockets, so apps don't get confused.
    """
    return -1

  @classmethod
  def pair(cls):
    """
    Retorna um par de soquetes conectados.
    :return: Par de soquetes conectados.
    """
    """ Return a pair of connected sockets """
    a_to_b = MessageChannel()
    b_to_a = MessageChannel()
    a = cls(a_to_b, b_to_a)
    b = cls(b_to_a, a_to_b)
    return (a,b)

class MessageChannel(object):
  """
  Um unidirecional confiável em ordem byte transmitir canal de mensagens.
  """
  """ A undirectional reliable in order byte stream message channel (think TCP half-connection)
  """
  def __init__(self):
    # Single element queue
    self.buffer = ""
    self.on_data = None
    self.on_data_running = False
    self.pending_on_datas = 0

  def send(self, msg):
    """
    Envia mensagens.
    :param msg: Mensagem à ser enviada.
    :return: Tamanho da mensagem.
    """
    self.buffer += msg
    self._trigger_on_data()
    return len(msg)

  def _trigger_on_data(self):
    """
    Redimensiona o tamanho do buffer.
    :return: Sem retorno.
    """
    self.pending_on_datas += 1
    if self.on_data_running:
      # avoid recursive calls to on_data
      return

    while self.pending_on_datas > 0 and len(self.buffer) > 0:
      self.pending_on_datas -= 1
      if self.on_data:
        self.on_data_running = True
        self.on_data(self, len(self.buffer))
        self.on_data_running = False
      else:
        break

  def recv(self, max_size=None):
    """
    Recupera e retornar os dados armazenados no buffer deste canal.
    :param max_size: tamanho máximo do buffer.
    :return: Mensagem recebida.
    """
    """ retrieve and return the data stored in this channel's buffer. If buffer is empty, return "" """
    if max_size and max_size < len(self.buffer):
      msg = self.buffer[0:max_size]
      self.buffer = self.buffer[max_size:]
    else:
      msg = self.buffer
      self.buffer = ""
    return msg

  def is_empty(self):
    """
    Verifica se o buffer está vazio.
    :return: Booleano.
    """
    return len(self.buffer) == 0

  def is_full(self):
    """
    Verifica se o buffer está cheio.
    :return: Falso (por quê o buffer sempre pode almentar de tamanho.).
    """
    #  buffer length not constrained currently
    return False

  def __len__(self):
    return len(self.buffer)
