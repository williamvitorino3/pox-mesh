#!/bin/sh -
# coding=utf-8

# Copyright 2011,2012,2013 James McCauley
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

# If you have PyPy 1.6+ in a directory called pypy alongside pox.py, we
# use it.
# Otherwise, we try to use a Python interpreter called python2.7, which
# is a good idea if you're using Python from MacPorts, for example.
# We fall back to just "python" and hope that works.

# TODO: Make runnable by itself (paths need adjusting, etc.).

''''true
export OPT="-u -O"
export FLG=""
if [ "$(basename $0)" = "debug-pox.py" ]; then
  export OPT=""
  export FLG="--debug"
fi

if [ -x pypy/bin/pypy ]; then
  exec pypy/bin/pypy $OPT "$0" $FLG "$@"
fi

if type python2.7 > /dev/null; then
  exec python2.7 $OPT "$0" $FLG "$@"
fi
exec python $OPT "$0" $FLG "$@"
'''

from __future__ import print_function  # Nova implementação do print, faz print "a", "b" ->>> 'a', 'b'

import logging
import logging.config
import os
import sys
import traceback
import time
import inspect
import types
import threading

import pox.core

core = None

import pox.openflow
from pox.lib.util import str_to_bool

# Função a ser executada no thread principal
_main_thread_function = None

try:
  import __pypy__
except ImportError:
  __pypy__ = None


def _do_import(name):
  """
  Try to import the named component.
  Returns its module name if it was loaded or False on failure.
  """

  """
  Tenta importar o componente.
  Retorna o nome do módulo se foi carregado ou False em caso de falha.
  """

  def show_fail():
    # Mostra a falha ocorrida
    traceback.print_exc()
    print("Could not import module:", name)

  def do_import2(base_name, names_to_try):
    '''
    Tenta importar as funçoes "names_to_try"
    do modulo "base_name".
    '''
    if len(names_to_try) == 0:
      print("Module not found:", base_name)
      return False

    name = names_to_try.pop(0)
    # Atribui a 1º posição da lista à "name".
    # Tratando "names_to_try"como uma fila.

    if name in sys.modules:
      # Verifica se "name" já foi importado.
      return name

    try:
      __import__(name, level=0)
      # Tenta importar o modulo em tempo de execução.
      return name
    except ImportError:
      # There are two cases why this might happen:
      # 1. The named module could not be found
      # 2. Some dependent module (import foo) or some dependent
      #    name-in-a-module (e.g., from foo import bar) could not be found.
      # If it's the former, we might try a name variation (e.g., without
      # a leading "pox."), but if we ultimately can't find the named
      # module, we just say something along those lines and stop.
      # On the other hand, if the problem is with a dependency, we should
      # print a stack trace so that it can be fixed.
      # Sorting out the two cases is an ugly hack.

      message = str(sys.exc_info()[1].args[0])
      # Atribui em forma de String, o 1° argumento do parametro "value"
      # retornado por "sys.exec_info()".
      s = message.rsplit(" ", 1)
      # Retorna uma lista de duas posições, contendo a quebra da string "message" em duas.
      # a mesma será separada no ultimo " " encontrado.

      # Sadly, PyPy isn't consistent with CPython here.
      # TODO: Check on this behavior in pypy 2.0.

      # PyPy não é consistente com python aqui.
      # Verificar este comportamento em pypy 2.0.
      if s[0] == "No module named" and (name.endswith(s[1]) or __pypy__):
        # Foi o que nós tentamos importar. (Caso 1)
        # Se temos outros nomes para tentar, então chamamos
        # o metodo recursivamente.
        return do_import2(base_name, names_to_try)
      elif message == "Import by filename is not supported.":
        print(message)
        import os.path
        # https://docs.python.org/2/library/os.path.html
        n = name.replace("/", ".").replace("\\", ".")
        # Subistitui todos os "/" por "." e os "\\" por ".";
        n = n.replace(os.path.sep, ".")
        # Subistitui todos os separadores padroes do sistema por ".";
        if n.startswith("pox.") or n.startswith("ext."):
          # Se n comeca com "pox." ou "ext.";
          n = n[4:]
          # O prefixo é retirado de n;
        print("Maybe you meant to run '%s'?" % (n,))
        # Sugere uma alternativa de bibliotea.
        return False
      else:
        # Isto significa que encontramos o módulo que procurávamos,
        # mas uma de suas dependências estava faltando.
        show_fail()
        return False
    except:
      # Havia algum outro tipo de exceção ao tentar carregar o módulo.
      # Basta imprimir um rastreamento e chamá-lo um dia.
      show_fail()
      return False

  return do_import2(name, ["pox." + name, name])
  # Chama a função recursivamente.


def _do_imports(components):
  """
  Import each of the listed components

  Returns map of component_name->name,module,members on success,
  or False on failure
  """
  """
  Importa uma lista de componentes.

  Retorna cada um dos componentes listados->nome, modulo, membros em
  caso de sucesso ou Falso em caso de falha.
  """

  done = {}
  for name in components:
    if name in done:
      # Nome já foi importado
      continue

    r = _do_import(name)
    # Tenta importar o componente.
    # r irá receber o nome do componente caso dê certo
    # e False caso dê errado
    if r is False:
      return False
    members = dict(inspect.getmembers(sys.modules[r]))
    # members recebe em forma de dicionário
    # os membros do modulo que r tem o nome.
    done[name] = (r, sys.modules[r], members)

  return done


def _do_launch(argv):
  component_order = []
  # Ordem dos componentes
  # Lista vazia

  components = {}
  # Componentes
  # Dicionario vazio

  curargs = {}
  # Argumentos atuais
  # Dicionario vazio

  pox_options = curargs
  # Opções do POX
  # Copia a referência do objeto curargs para pox_options

  for arg in argv:
    # arg(argumento)
    if not arg.startswith("-"):  # Se arg não inicia com "-"
      if arg not in components:  # Se arg não estiver em componentes
        components[arg] = []  # Adiciona uma lista vazia para a chave arg
      curargs = {}  # Reatribui um dicionario vazio a curargs
      components[arg].append(curargs)  # Adiciona curargs a lista de componentes na posicao arg
      component_order.append(arg)  # Adiciona arg a lista de ordem dos componentes
  else:  # Se arg inicia com "-"
    arg = arg.lstrip("-").split("=", 1)
    # Retira "-" arg e atribui uma lista de string com uma ou duas substrings
    # da arg, separadas por "=".
    arg[0] = arg[0].replace("-", "_")  # Substitui todos os "-" por "_" de agr[0]
    if len(arg) == 1:  # Se arg[0] for uma lista de uma só posicao
      arg.append(True)  # Adiciona True no final
    curargs[arg[0]] = arg[1]
    # atribui o valor de arg[1] em curargs na posicao corespondente à string arg[0]

  _options.process_options(pox_options)
  # Se a opção for desconhecida encerra o processo.

  global core
  # Chama o objeto core como global
  if pox.core.core is not None:  # Verififar arquivo core
    core = pox.core.core
    core.getLogger('boot').debug('Using existing POX core')
  else:
    core = pox.core.initialize(_options.threaded_selecthub,
                               _options.epoll_selecthub,
                               _options.handle_signals)
  # Só quando olhar a core.py
  _pre_startup()
  # Todas as opções do POX foram lidas.
  modules = _do_imports(n.split(':')[0] for n in component_order)
  # Modulos recebe uma lista com:
  #     -> Dicionario, contendo informações sobre os modulos importados.
  #     -> False, se não for possível importar o módulo
  if modules is False:
    return False

  inst = {}
  # Dicionário vazio

  for name in component_order:
    # Passapor todos os componentes da lista component_order
    # atribui esse valos a name.
    cname = name
    # pra que serve "cname"?

    inst[name] = inst.get(name, -1) + 1
    # Atribui ao dicionario na chave "name", oq ele contiver com essa chave + 1
    # ou -1 + 1 se ele não tiver uma chave "name".
    params = components[name][inst[name]]
    # params recebe o valor dos componentes na chave name na posição
    # correspondente ao valor de inst[name].
    name = name.split(":", 1)
    # Atribui a name uma lista de strings com a string name quebrada
    # em no máximo duas posições, quebra essa feita no primeiro
    # caracter ":" que aparecer.

    launch = name[1] if len(name) == 2 else "launch"
    # launch recebe a segunda posicao da linta name, se ela contiver
    # duas posicoes, se não, ele recebe a string "launch".

    name = name[0]
    # name recebe a string da primeira posicao da lista name.

    name, module, members = modules[name]
    # Pega os elementos de modules na chave name e atribui às variáveis
    # simultaneamente. (Atribuição multipla)

    if launch in members:  # Se launch estiver em members
      f = members[launch]
      # atribui o mendo com a chave saunch à f

      # We explicitly test for a function and not an arbitrary callable.
      # Testamos explicitamente para uma função e não um arbitrário callable.
      if type(f) is not types.FunctionType:  # Se f não for uma função
        print(launch, "in", name, "isn't a function!")  # Diz não é uma função
        return False  # Retorna falso

      if getattr(f, '_pox_eval_args', False):
        # Verifica se o metodo '_pox_eval_args' existe em f.
        import ast
        '''
        O módulo ast ajuda aplicações Python para processar árvores do Python
        sintaxe abstrata gramática. A própria sintaxe abstrata pode mudar com
        cada versão Python; Este módulo ajuda a descobrir programaticamente
        o que a gramática atual se parece.
        '''

        for k, v in params.items():  # Declarado na linha 267
          #  Copia a chave -> k e o valor -> v das posições do dicionario params.
          if isinstance(v, str):
            # Se o objeto v é da classe string.
            try:
              params[k] = ast.literal_eval(v)
              # Verifica se o valor de v é código python
            except:
              # Leave it as a string
              pass

      multi = False
      if f.__code__.co_argcount > 0:  # Se a função f receber algum argumento.
        # FIXME: This code doesn't look quite right to me and may be broken
        #       in some cases.  We should refactor to use inspect anyway,
        #       which should hopefully just fix it.
        '''
        FIXME: Esse código não parece muito bem para mim e pode ser quebrado em alguns
        casos. Nós devemos refatorar para uso de qualquer forma, inspecionar
        que esperemos que deve apenas corrigi-lo.
        '''
        if (f.__code__.co_varnames[f.__code__.co_argcount - 1]
              == '__INSTANCE__'):
          # It's a multi-instance-aware component.
          # É um componente de reconhecimento de instância de multipla.

          multi = True

          # Special __INSTANCE__ paramter gets passed a tuple with:
          # 1. The number of this instance (0...n-1)
          # 2. The total number of instances for this module
          # 3. True if this is the last instance, False otherwise
          # The last is just a comparison between #1 and #2, but it's
          # convenient.

          # Parâmetro especial __INSTANCE__ é passado uma tupla com:
          # 1. O numero da instancia(0...n-1)
          # O total de instancias deste módulo.
          # 3. True se esta for a ultima instancia, False so não.
          # O último é apenas uma comparação entre o #1 e #2, mas é conveniente.


          params['__INSTANCE__'] = (inst[cname], len(components[cname]),
                                    inst[cname] + 1 == len(components[cname]))

      if multi == False and len(components[cname]) != 1:
        # Verifica se existe mais de um objeto de multi.
        print(name, "does not accept multiple instances")
        return False
        # Cansei... Vou pular isso... Fllw
      try:
        if f(**params) is False:
          # Abort startup
          return False
      except TypeError as exc:
        instText = ''
        if inst[cname] > 0:
          instText = "instance {0} of ".format(inst[cname] + 1)
        print("Error executing {2}{0}.{1}:".format(name, launch, instText))
        if inspect.currentframe() is sys.exc_info()[2].tb_frame:
          # Error is with calling the function
          # Try to give some useful feedback
          if _options.verbose:
            traceback.print_exc()
          else:
            exc = sys.exc_info()[0:2]
            print(''.join(traceback.format_exception_only(*exc)), end='')
          print()
          EMPTY = "<Unspecified>"
          code = f.__code__
          argcount = code.co_argcount
          argnames = code.co_varnames[:argcount]
          defaults = list((f.func_defaults) or [])
          defaults = [EMPTY] * (argcount - len(defaults)) + defaults
          args = {}
          for n, a in enumerate(argnames):
            args[a] = [EMPTY, EMPTY]
            if n < len(defaults):
              args[a][0] = defaults[n]
            if a in params:
              args[a][1] = params[a]
              del params[a]
          if '__INSTANCE__' in args:
            del args['__INSTANCE__']

          if f.__doc__ is not None:
            print("Documentation for {0}:".format(name))
            doc = f.__doc__.split("\n")
            # TODO: only strip the same leading space as was on the first
            #      line
            doc = map(str.strip, doc)
            print('', ("\n ".join(doc)).strip())

          # print(params)
          # print(args)

          print("Parameters for {0}:".format(name))
          if len(args) == 0:
            print(" None.")
          else:
            print(" {0:25} {1:25} {2:25}".format("Name", "Default",
                                                 "Active"))
            print(" {0:25} {0:25} {0:25}".format("-" * 15))

            for k, v in args.iteritems():
              print(" {0:25} {1:25} {2:25}".format(k, str(v[0]),
                                                   str(v[1] if v[1] is not EMPTY else v[0])))

          if len(params):
            print("This component does not have a parameter named "
                  + "'{0}'.".format(params.keys()[0]))
            return False
          missing = [k for k, x in args.iteritems()
                     if x[1] is EMPTY and x[0] is EMPTY]
          if len(missing):
            print("You must specify a value for the '{0}' "
                  "parameter.".format(missing[0]))
            return False

          return False
        else:
          # Error is inside the function
          raise
    elif len(params) > 0 or launch is not "launch":
      print("Module %s has no %s(), but it was specified or passed " \
            "arguments" % (name, launch))
      return False

  return True


class Options(object):
  def set(self, given_name, value):
    name = given_name.replace("-", "_")
    # Substitui os "-" de given_namepor "_" e atribui à name
    if name.startswith("_") or hasattr(Options, name):
      # Verifica se name inicia com "_"
      # Verifica se given_name pertence à classe Options.
      # Hey, what's that about?
      print("Illegal option:", given_name)
      return False
    has_field = hasattr(self, name)
    # Verifica se name pertence ao objeto self.
    has_setter = hasattr(self, "_set_" + name)
    # Verifica se o objeto self tem um setter para name.
    if has_field == False and has_setter == False:
      # Name desconhecido para a classe Options.
      print("Unknown option:", given_name)
      return False
    if has_setter:  # Se tiver setter.
      setter = getattr(self, "_set_" + name)
      # getattr == O valor do atributo "nome" do objeto.
      # Atribui a setter o valor do retorno da função.
      setter(given_name, name, value)  # Seta os atributos.
    else:
      if isinstance(getattr(self, name), bool):
        # Verifica se name é um atributo booleano.
        # Automatic bool-ization
        value = str_to_bool(value)
        # Transforma value em string.
      setattr(self, name, value)
      # Atribui value ao atributo name do objeto self.
    return True

  # Fecha set.

  def process_options(self, options):
    for k, v in options.iteritems():
      if self.set(k, v) is False:
        # Opção options[k] desconhecida para a classe Options.
        # Bad option!
        sys.exit(1)
        # Fecha o processo informando que ouve erro.


_help_text = """
POX is a Software Defined Networking controller framework.

The commandline of POX is like:
pox.py [POX options] [C1 [C1 options]] [C2 [C2 options]] ...

Notable POX options include:
  --verbose       Print more debugging information (especially useful for
                  problems on startup)
  --no-openflow   Don't automatically load the OpenFlow module
  --log-config=F  Load a Python log configuration file (if you include the
                  option without specifying F, it defaults to logging.cfg)

C1, C2, etc. are component names (e.g., Python modules).  Options they
support are up to the module.  As an example, you can load a learning
switch app that listens on a non-standard port number by specifying an
option to the of_01 component, and loading the l2_learning component like:
  ./pox.py --verbose openflow.of_01 --port=6634 forwarding.l2_learning

The 'help' component can give help for other components.  Start with:
  ./pox.py help --help
""".strip()


class POXOptions(Options):  # Classe filha da classe Options.
  def __init__(self):
    #    self.cli = True
    self.verbose = False
    self.enable_openflow = True
    self.log_config = None
    self.threaded_selecthub = True
    self.epoll_selecthub = False
    self.handle_signals = True

  def _set_h(self, given_name, name, value):
    self._set_help(given_name, name, value)
    # Chama metodo que mostra texto de ajuda e fecha o processo.

  def _set_help(self, given_name, name, value):
    print(_help_text)
    # TODO: Summarize options, etc.
    sys.exit(0)
    # Mostra texto de ajuda e fecha o processo.

  def _set_version(self, given_name, name, value):
    global core
    # Pega a variável core do arquivo como global.
    if core is None:  # Se core não tiver cido inicializada.
      core = pox.core.initialize()  # Inicializa o objeto.
    print(core._get_python_version())  # Pinta a verção do core.
    sys.exit(0)  # Encerra o processo.

  def _set_unthreaded_sh(self, given_name, name, value):
    self.threaded_selecthub = False
    # Atualiza o valor do parametro threaded_selecthub do objeto POXOprtions

  def _set_epoll_sh(self, given_name, name, value):
    self.epoll_selecthub = str_to_bool(value)
    # Atribui valor ao parametro epoll_selecthub do objeto POXOptions

  def _set_no_openflow(self, given_name, name, value):
    self.enable_openflow = not str_to_bool(value)
    # Atribui valor ao parametro enable_openflow do objeto POXOptions

  #  def _set_no_cli (self, given_name, name, value):
  #    self.cli = not str_to_bool(value)

  def _set_log_config(self, given_name, name, value):
    if value is True:
      # I think I use a better method for finding the path elsewhere...
      p = os.path.dirname(os.path.realpath(__file__))
      # Atribui a p o diretorio em q __file__ está.
      value = os.path.join(p, "..", "logging.cfg")
      # Atribui a value o local onde logging.cfg está.
    self.log_config = value
    # Atribui o valor de Value ao parametro log_config do objeto POXOptions

  def _set_debug(self, given_name, name, value):
    value = str_to_bool(value)
    # Pega um valor booleano a partir de value
    if value:  # Se value for verdadeiro
      # Debug implies no openflow and no CLI and verbose
      # TODO: Is this really an option we need/want?
      self.verbose = True
      # Atribui Verdadeiro ao atributo verbose do objeto POXOptions
      self.enable_openflow = False
      # Atribui Falso ao atributo enable_openflow do objeto POXOptions
      # self.cli = False


_options = POXOptions()


# Cria um Objeto POXOptions


def _pre_startup():
  """
  This function is called after all the POX options have been read in
  but before any components are loaded.  This gives a chance to do
  early setup (e.g., configure logging before a component has a chance
  to try to log something!).

  Essa função é chamada depois que todas as opções do POX foram lidas,
  mas antes de todos os componentes serem carregados.
  Isso dá uma chance para fazer a configuração inicial
  (por exemplo, configurar o log antes que um componente tenha
  uma chance para tentar registrar algo!).
  """

  _setup_logging()
  # Configura o arquivo de logging

  if _options.verbose:
    logging.getLogger().setLevel(logging.DEBUG)
    # Seta o level do logging para debug

  if _options.enable_openflow:
    pox.openflow._launch()  # Default OpenFlow launch
    # Lancamento padrão do OpenFlow


"""
    Ver arquivos:
    -> _options
    -> core
    -> openflow.of_01
"""


def _post_startup():
  if _options.enable_openflow:
    # Se o openflow do objeto _options estiver habilitado
    if core._openflow_wanted:
      # Se o core estiver em espera
      if not core.hasComponent("of_01"):
        # Launch a default of_01
        import pox.openflow.of_01  # Importa esse arquivo.
        pox.openflow.of_01.launch()
        # roda o openflow.
    else:
      logging.getLogger("boot").debug("Not launching of_01")
      # Debuga o log.


def _setup_logging():
  # First do some basic log config...

  # Primeiro algumas configurações de log básico.

  # This is kind of a hack, but we need to keep track of the handler we
  # install so that we can, for example, uninstall it later.  This code
  # originally lived in pox.core, so we explicitly reference it here.
  """
  Este é tipo de um hack, mas precisamos acompanhar o manipulador que
  vamos instalar para que nós possamos, por exemplo, desinstalá-lo mais tarde.
  Este código, originalmente, viviam em pox.core, então nós vamos explicitamente
  referenciá-lo aqui.
  """

  pox.core._default_log_handler = logging.StreamHandler()
  formatter = logging.Formatter(logging.BASIC_FORMAT)
  pox.core._default_log_handler.setFormatter(formatter)
  logging.getLogger().addHandler(pox.core._default_log_handler)
  logging.getLogger().setLevel(logging.INFO)

  # Now set up from config file if specified...

  # Agora configure do arquivo de configuração se especificada...

  # TODO:
  #  I think we could move most of the special log stuff into
  #  the log module.  You'd just have to make a point to put the log
  #  module first on the commandline if you wanted later component
  #  initializations to honor it.  Or it could be special-cased?

  if _options.log_config is not None:
    if not os.path.exists(_options.log_config):
      print("Could not find logging config file:", _options.log_config)
      sys.exit(2)
    logging.config(_options.log_config, disable_existing_loggers=True)
    # Lê a configuração do arquivo ConfigParser formato _options.log_config.


def set_main_function(f):
  global _main_thread_function
  if _main_thread_function == f: return True
  if _main_thread_function is not None:
    import logging
    lg = logging.getLogger("boot")
    lg.error("Could not set main thread function to: " + str(f))
    lg.error("The main thread function is already "
             + "taken by: " + str(_main_thread_function))
    return False
  _main_thread_function = f
  return True


# Inicia o OpenFlow
def boot(argv=None):
  """
  Start up POX.

  Inicia POX.
  """

  # Adiciona o diretorio pox à path do python
  base = sys.path[0]
  '''
  sys.path[0] é o diretório que contém o script que foi usado para chamar
  o interpretador Python.
  '''
  sys.path.insert(0, os.path.abspath(os.path.join(base, 'pox')))
  sys.path.insert(0, os.path.abspath(os.path.join(base, 'ext')))

  thread_count = threading.active_count()
  # Retorna a quantidade de threads ativas

  quiet = False

  try:
    if argv is None:
      argv = sys.argv[1:]

    # Sempre carrega cli (primeiro!)
    # TODO: Can we just get rid of the normal options yet?
    pre = []
    # pre recebe uma lista vázia.
    while len(argv):  # Enquanto argv não estiver vázio.
      if argv[0].startswith("-"):  # Se a primeira posição começar com "-".
        pre.append(argv.pop(0))
        # Remove a primeira posição de argv e adiciona no final de pre.
      else:
        break
        # Sai do laço.
    argv = pre + "py --disable".split() + argv
    # Atribui a argv a concatenação destas listas.

    if _do_launch(argv):  # Se o objeto pode ser carregado.
      _post_startup()  # Inicia OpenFlow
      core.goUp()  # Faz alguma coisa.
    else:
      quiet = True  # Atribui a True para essa variável
      raise RuntimeError()  # Cria um RubtimeError.

  except SystemExit:  # Se ocorrer o erro SystemExit.
    return  # Sai da função.
  except:  # Qualquer outra exeção.
    if not quiet:  # Se não estiver quieto
      traceback.print_exc()  # Printa a exceção.

    # Try to exit normally, but do a hard exit if we don't.
    # Tente sair normalmente, mas fazer uma saída difícil, se não o fizermos.
    # This is sort of a hack.  What's the better option?  Raise
    # the going down event on core even though we never went up?

    try:
      for _ in range(4):
        if threading.active_count() <= thread_count:  # Verifica se a thread atual é a q está no contador.
          # Normal exit
          return
        time.sleep(0.25)
    except:
      pass

    os._exit(1)   # Saída com algum erro.
    return

  if _main_thread_function:
    _main_thread_function()
    # Função principal à ser executada.
  else:
    # core.acquire()
    try:
      while True:
        if core.quit_condition.acquire(False):
          core.quit_condition.wait(10)
          core.quit_condition.release()
        if not core.running:  # Se o core não estiver rodando...
          break   # Sai do laço.
    except:
      pass
      # core.scheduler._thread.join() # Sleazy

  try:
    pox.core.core.quit()    # Fecha o core.
  except:
    pass
