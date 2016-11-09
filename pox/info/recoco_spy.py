# Copyright 2012 James McCauley
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

"""
This is an extremely primitive start at some debugging.
At the moment, it is really just for recoco (maybe it belongs in there?).
"""
"""
Este é um começo extremamente primitivo em alguma depuração.
No momento, é realmente apenas para rococo (talvez ele pertence lá?).
"""

from pox.core import core
log = core.getLogger()
import time
import traceback
import pox.lib.recoco

_frames = []

def _tf (frame, event, arg):
  """
  Gerência a lista de quadros.
  :param frame: Quadro Ethernet.
  :param event: Evento relacionado à chamada da função.
  :param arg: Argumentos do quadro.
  :return: Refencia da própria função.
  """
  if _frames is None: return _tf
  #print " " * len(_frames) + event
  if event == 'call':
    _frames.append(frame)
    return _tf
  elif event == 'line':
    return _tf
  elif event == 'exception':
    #_frames.pop()
    return _tf
  elif event == 'return':
    _frames.pop()
  elif event == 'c_call':
    print "c_call"
    _frames.append((frame,arg))
  elif event == 'c_exception':
    _frames.pop()
  elif event == 'c_return':
    _frames.pop()


def _trace_thread_proc ():
  """
  Percorre todos os quadros da lista à procura de alguma irregularidade.
  :return: Sem retorno.
  """
  last = None
  last_time = None
  warned = None
  while True:
    try:
      time.sleep(1)
      c = len(_frames)
      if c == 0: continue
      f = _frames[-1]
      stopAt = None
      count = 0
      sf = f
      # Roda todos os quadros.
      while sf is not None: # Enquanto o quadro não estiver vazio.
        if sf.f_code == pox.lib.recoco.Scheduler.cycle.im_func.func_code:   # Verifica se as funções são iguais.
          stopAt = sf # Identifica o quadro de parada.
          break # Sai do laço.
        # Se não.
        count += 1  # Incrementa o contador.
        sf = sf.f_back  # Pega o próximo quadro.
      #if stopAt == None: continue

      f = "\n".join([s.strip() for s in
                      traceback.format_stack(f,count)])
      #f = " / ".join([s.strip() for s in
      #                traceback.format_stack(f,1)[0].strip().split("\n")])
      #f = "\n".join([s.strip() for s in
      #                traceback.format_stack(f)])

      if f != last:   # Se f não for o último.
        if warned:  # Se já avisou...
          log.warning("Running again")  # Lança o aviso.
        warned = None   # Restalra o valor da variável.
        last = f  # f se torna o último quadro.
        last_time = time.time() # Pega o tempo que passou.
      elif f != warned:   # Se não tiver avisado.
        if time.time() - last_time > 3: # Se o tempo percorrido - o tempo final for maior que 3.
          if stopAt is not None:  # Se a padara não for None.
            warned = f    # avisado recebe o quadro f
            log.warning("Stuck at:\n" + f)  # Lança o aviso para o usuário.

      #from pox.core import core
      #core.f = f

    except: # Caso ocorra qualquer erro.
      traceback.print_exc() # Mostra o erro.
      pass



def launch ():
  """
  Lança nova thread de _trace_thread_proc.
  :return: Sem retorno.
  """
  def f ():
    import sys
    sys.settrace(_tf)
  core.callLater(f)

  import threading
  _trace_thread = threading.Thread(target=_trace_thread_proc)
  _trace_thread.daemon = True
  _trace_thread.start()
