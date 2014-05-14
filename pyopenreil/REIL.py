from abc import ABCMeta, abstractmethod
from sets import Set

IOPT_CALL    = 0x00000001
IOPT_RET     = 0x00000002
IOPT_BB_END  = 0x00000004
IOPT_ASM_END = 0x00000008

MAX_INST_LEN = 30

def create_globals(items, prefix):

    num = 0
    for it in items:

        globals()[prefix + str(it)] = num
        num += 1

REIL_INSN = [ 'NONE', 'JCC', 
              'STR', 'STM', 'LDM', 
              'ADD', 'SUB', 'NEG', 'MUL', 'DIV', 'MOD', 'SMUL', 'SDIV', 'SMOD', 
              'SHL', 'SHR', 'ROL', 'ROR', 'AND', 'OR', 'XOR', 'NOT',
              'EQ', 'NEQ', 'L', 'LE', 'SL', 'SLE', 
              'CAST_L', 'CAST_H', 'CAST_U', 'CAST_S' ]

REIL_SIZE = [ '1', '8', '16', '32', '64' ]

REIL_ARG = [ 'NONE', 'REG', 'TEMP', 'CONST' ]

create_globals(REIL_INSN, 'I_')
create_globals(REIL_SIZE, 'U')
create_globals(REIL_ARG, 'A_')

import translator
from arch import x86

class SymVal:

    def __init__(self, val, size):

        self.val = val
        self.size = size

    def __str__(self):

        return str(self.val)

    def __eq__(self, other):

        if other.__class__ == SymAny: return True
        if other.__class__ != SymVal: return False

        return self.val == other.val

    def __ne__(self, other):

        return not self == other

    def __hash__(self):

        return hash(self.val)

    def __add__(self, other): 

        return self.to_exp(I_ADD, other)    

    def __sub__(self, other): 

        return self.to_exp(I_SUB, other)    

    def __mul__(self, other): 

        return self.to_exp(I_MUL, other)

    def __mod__(self, other): 

        return self.to_exp(I_MOD, other)    

    def __div__(self, other): 

        return self.to_exp(I_DIV, other)        

    def __and__(self, other): 

        return self.to_exp(I_AND, other)    

    def __xor__(self, other): 

        return self.to_exp(I_XOR, other)    

    def __or__(self, other): 

        return self.to_exp(I_OR, other)  

    def __lshift__(self, other): 

        return self.to_exp(I_SHL, other)    

    def __rshift__(self, other): 

        return self.to_exp(I_SHR, other) 

    def __invert__(self): 

        return self.to_exp(I_NOT)    

    def __neg__(self): 

        return self.to_exp(I_NEG)      

    def to_exp(self, op, arg = None):

        return SymExp(op, self, arg)  


class SymAny(SymVal):

    def __init__(self): 

        pass

    def __str__(self):

        return '@'

    def __eq__(self, other):

        return True


class SymPtr(SymVal):

    def __init__(self, val): 

        self.val = val

    def __str__(self):

        return '*' + str(self.val)

    def __eq__(self, other):

        if other.__class__ == SymAny: return True
        if other.__class__ != SymPtr: return False

        return self.val == other.val

    def __hash__(self):

        return ~hash(self.val)


class SymConst(SymVal):

    def __str__(self):

        return '0x%x' % self.val

    def __eq__(self, other):

        if other.__class__ == SymAny: return True
        if other.__class__ != SymConst: return False

        return self.val == other.val


class SymExp(SymVal):

    commutative = ( I_ADD, I_SUB, I_AND, I_XOR, I_OR )

    def __init__(self, op, a, b = None):

        self.op, self.a, self.b = op, a, b

    def __str__(self):

        items = [ 'I_' + REIL_INSN[self.op] ]
        if self.a is not None: items.append(str(self.a))
        if self.b is not None: items.append(str(self.b))

        return '(%s)' % ' '.join(items)

    def __eq__(self, other):

        if other.__class__ == SymAny: return True
        if other.__class__ != SymExp: return False

        if self.op == other.op and self.op in self.commutative:

            # equation for commutative operations
            return (self.a == other.a and self.b == other.b) or \
                   (self.b == other.a and self.a == other.b)

        return self.op == other.op and \
               self.a == other.a and self.b == other.b

    def __hash__(self):

        return hash(self.op) + hash(self.a) + hash(self.a)


class SymState:

    def __init__(self, other = None):

        if other is None: self.clear()
        else: self.items = other.items.copy()

    def __getitem__(self, n):

        return self.items[n]

    def __str__(self):

        return '\n'.join(map(lambda k: '%s: %s' % (k, self.items[k]), self.items))

    def clear(self):

        self.items = {}

    def update(self, val, exp):

        self.items[val] = exp

    def update_mem(self, val, exp):

        self.update(SymPtr(self.items[val]), exp)

    def clone(self):

        return SymState(self)


class Arg:

    def __init__(self, t = None, size = None, name = None, val = None):

        self.type = A_NONE if t is None else t
        self.size = None if size is None else size
        self.name = None if name is None else name
        self.val = 0L if val is None else long(val)

    def get_val(self):

        mkval = lambda mask: long(self.val & mask)

        if self.size == U1:    return 0 if mkval(0x1) == 0 else 1
        elif self.size == U8:  return mkval(0xff)
        elif self.size == U16: return mkval(0xffff)
        elif self.size == U32: return mkval(0xffffffff)
        elif self.size == U64: return mkval(0xffffffffffffffff)

    def __str__(self):

        mkstr = lambda val: '%s:%s' % (val, REIL_SIZE[self.size])

        if self.type == A_NONE:    return ''
        elif self.type == A_REG:   return mkstr(self.name)
        elif self.type == A_TEMP:  return mkstr(self.name)
        elif self.type == A_CONST: return mkstr('%x' % self.get_val())

    def serialize(self):

        if self.type in [ A_REG, A_TEMP ]: return self.type, self.size, self.name
        elif self.type == A_NONE: return ()
        else: return self.type, self.size, self.val

    def unserialize(self, data):

        if len(data) == 3:

            value = data[2]            
            self.type, self.size = data[0], data[1]            

            if self.size not in [ U1, U8, U16, U32, U64 ]:

                raise(Exception('Invalid operand size'))            
            
            if self.type == A_REG: self.name = value
            elif self.type == A_TEMP: self.name = value
            elif self.type == A_CONST: self.val = value
            else: 

                raise(Exception('Invalid operand type'))

        elif len(data) == 0:

            self.type = A_NONE
            self.size = self.name = None 
            self.val = 0L

        else: raise(Exception('Invalid operand'))

    def is_var(self):

        # check for temporary or target architecture register
        return self.type == A_REG or self.type == A_TEMP


# raw translated REIL instruction parsing
Insn_addr  = lambda insn: insn[0][0] # instruction virtual address
Insn_size  = lambda insn: insn[0][1] # assembly code size
Insn_inum  = lambda insn: insn[1]    # IR subinstruction number
Insn_op    = lambda insn: insn[2]    # operation code
Insn_args  = lambda insn: insn[3]    # tuple with 3 arguments
Insn_flags = lambda insn: insn[4]    # instruction flags

class Insn:    

    def __init__(self, op = None, a = None, b = None, c = None):

        serialized = None
        if isinstance(op, tuple): 
            
            serialized = op
            op = None

        self.addr, self.inum, self.ir_addr = 0L, 0, ()
        self.op = I_NONE if op is None else op
        self.a = Arg() if a is None else a
        self.b = Arg() if b is None else b
        self.c = Arg() if c is None else c

        # unserialize raw IR instruction structure
        if serialized: self.unserialize(serialized)

    def __str__(self):

        return '%.8x.%.2x %7s %16s, %16s, %16s' % \
               (self.addr, self.inum, REIL_INSN[self.op], \
                self.a, self.b, self.c)

    def serialize(self):

        info = ( self.addr, self.size )
        args = ( self.a.serialize(), self.b.serialize(), self.c.serialize() )
        
        return ( info, self.inum, self.op, args, self.flags )

    def unserialize(self, data):

        self.addr, self.size = Insn_addr(data), Insn_size(data) 
        self.inum, self.flags = Insn_inum(data), Insn_flags(data)
        self.ir_addr = (self.addr, self.inum)

        self.op = Insn_op(data)
        if self.op > len(REIL_INSN) - 1:

            raise(Exception('Invalid operation code'))

        args = Insn_args(data) 
        if len(args) != 3: raise(Exception('Invalid arguments'))

        self.a.unserialize(args[0])
        self.b.unserialize(args[1])
        self.c.unserialize(args[2])
        return self

    def have_flag(self, val):

        return self.flags & val != 0

    def dst(self):

        ret = []

        if self.op != I_JCC and self.op != I_STM and \
           self.c.is_var(): ret.append(self.c)

        return ret

    def src(self):

        ret = []
        
        if self.a.is_var(): ret.append(self.a)
        if self.b.is_var(): ret.append(self.b)

        if (self.op == I_JCC or self.op == I_STM) and \
           self.c.is_var(): ret.append(self.c)

        return ret

    def to_symbolic(self, in_state = None):

        # copy input state to output state
        out_state = SymState() if in_state is None else in_state.clone()

        # skip instructions that doesn't update output state
        if self.op in [ I_JCC, I_NONE ]: return out_state

        def _to_symbolic_arg(arg):

            if arg.type == A_REG or arg.type == A_TEMP:

                # register value
                arg = SymVal(arg.name, arg.size)

                try: return out_state[arg]
                except KeyError: return arg

            elif arg.type == A_CONST:

                # constant value
                return SymConst(arg.get_val(), arg.size)

            else: return None

        # convert source arguments to symbolic expressions
        a = _to_symbolic_arg(self.a)
        b = _to_symbolic_arg(self.b)
        c = SymVal(self.c.name, self.c.size)

        # constant argument should always be second
        if a.__class__ == SymConst and b.__class__ == SymVal: a, b = b, a

        # move from one register to another
        if self.op == I_STR: out_state.update(c, a)

        # memory read
        elif self.op == I_LDM: out_state.update(c, SymPtr(a))

        # memory write
        elif self.op == I_STM: out_state.update_mem(c, a)

        # expression
        else: out_state.update(c, a.to_exp(self.op, b))

        return out_state

    def next(self):

        if self.have_flag(IOPT_RET): 

            # end of function
            return None

        elif self.op == I_JCC and \
             self.a.type == A_CONST and self.a.get_val() != 0 and \
             not self.have_flag(IOPT_CALL):

            # unconditional jump
            return None

        elif self.have_flag(IOPT_ASM_END):

            # go to first IR instruction of next assembly instruction
            return self.addr + self.size, 0

        else:

            # go to next IR instruction of current assembly instruction
            return self.addr, self.inum + 1

    def jcc_loc(self):

        if self.op == I_JCC and self.c.type == A_CONST: return self.c.get_val(), 0
        return None


class Reader:

    __metaclass__ = ABCMeta

    @abstractmethod
    def read(self, addr, size): pass

    @abstractmethod
    def read_insn(self, addr): pass


class ReaderRaw(Reader):

    def __init__(self, data, addr = 0L):

        self.addr = addr
        self.data = data
        Reader.__init__(self)

    def read(self, addr, size): 

        if addr < self.addr or \
           addr >= self.addr + len(self.data): return None

        addr -= self.addr        
        return self.data[addr : addr + size]

    def read_insn(self, addr): 

        return self.read(addr, MAX_INST_LEN)

        
class Storage:

    __metaclass__ = ABCMeta

    @abstractmethod
    def query(self, addr): pass

    @abstractmethod
    def store(self, insn): pass


class StorageMemory(Storage):

    def __init__(self, insn_list = None): 

        self.clear()
        if insn_list is not None: self.store(insn_list)

    def __iter__(self):

        keys = self.items.keys()
        keys.sort()

        for k in keys: yield Insn(self.items[k])

    def clear(self):

        self.items = {}

    def get_key(self, insn):

        return Insn_addr(insn), Insn_inum(insn)

    def to_file(self, path):

        with open(path, 'w') as fd:

            # dump all instructions to the text file
            for insn in self: fd.write(str(insn.serialize()) + '\n')

    def from_file(self, path):

        with open(path) as fd:        
        
            for line in fd:

                line = eval(line.strip())
                if isinstance(line, tuple): self._store(line)
    
    def query(self, addr, inum = None): 

        ret = []

        if inum is None: 

            inum = 0
            query_single = False

        else:

            query_single = True

        while True:

            # query single IR instruction
            insn = Insn(self.items[(addr, inum)])
            if query_single: return insn

            next = insn.next()
            ret.append(insn)

            # stop on assembly instruction end
            if insn.have_flag(IOPT_ASM_END): break
            inum += 1

        return ret

    def _store(self, insn):

        self.items[self.get_key(insn)] = insn

    def store(self, insn_or_insn_list): 

        if isinstance(insn_or_insn_list, list):

            # store instructions list
            for insn in insn_or_insn_list: self._store(insn)

        else:

            # store single IR instruction
            self._store(insn_or_insn_list)


class BasicBlock:
    
    def __init__(self, insn_list):

        self.insn_list = insn_list
        self.first, self.last = insn_list[0], insn_list[-1]
        self.addr, self.inum = self.first.addr, self.first.inum
        self.size = self.last.addr + self.last.size - self.addr

    def __iter__(self):

        for insn in self.insn_list: yield insn

    def __str__(self):

        return '\n'.join(map(lambda insn: str(insn), self))

    def get_successors(self):

        return self.last.next(), self.last.jcc_loc()


class Cfg:

    __metaclass__ = ABCMeta

    @abstractmethod
    def get_insn(self, addr): pass

    def process_node(self, bb): return True
    def process_edge(self, bb_from, bb_to): return True

    def _get_bb(self, addr):

        insn_list = []
        
        while True:

            # translate single assembly instruction
            insn_list += self.get_insn(addr)
            insn = insn_list[-1]

            # check for basic block end
            if insn.have_flag(IOPT_BB_END): break

            addr += insn.size

        return insn_list    

    def get_bb(self, addr, inum = None):

        inum = 0 if inum is None else inum
        last = inum

        # translate basic block at given address
        insn_list = self._get_bb(addr)        

        for insn in insn_list[inum:]:

            last += 1
            if insn.have_flag(IOPT_BB_END): 

                return BasicBlock(insn_list[inum:last])

    def traverse(self, addr):

        stack, nodes, edges = [], [], []
        stack_top = addr

        def _stack_push(addr, inum):

            if ( addr, inum ) not in nodes: stack.append(addr)

        def _process_node(insn_list):

            v = ( insn_list[0].addr, insn_list[0].inum )
            if v not in nodes:
            
                nodes.append(v)
                return self.process_node(BasicBlock(insn_list))

            return True    

        def _process_edge(bb, bb_to):  

            bb_from = ( bb[0].addr, bb[0].inum )

            e = ( bb_from, bb_to )
            if e not in edges:

                edges.append(e)
                return self.process_edge(BasicBlock(bb), self.get_bb(*bb_to))
                
            return True  

        # iterative pre-order CFG traversal
        while True:

            # translate basic block at given address
            insn_list = self._get_bb(stack_top)
            bb = []

            for insn in insn_list:

                bb.append(insn)

                # split assembly basic block into the IR basic blocks
                if insn.have_flag(IOPT_BB_END): 

                   if not _process_node(bb): return False

                   lhs, rhs = insn.next(), insn.jcc_loc()
                   if rhs is not None: 

                        if not _process_edge(bb, rhs): return False
                        _stack_push(*rhs)

                   if lhs is not None: 

                        if not _process_edge(bb, lhs): return False
                        _stack_push(*lhs)

                   bb = []
            
            try: stack_top = stack.pop()
            except IndexError: break
            
        return map(lambda bb: self.get_bb(*bb), nodes)
            

class CfgParser(Cfg):

    def __init__(self, storage, visitor = None):

        self.visitor = visitor
        self.storage = storage

    def process_node(self, bb):

        if self.visitor: return self.visitor(bb)
        return True

    def get_insn(self, addr, inum = None):

        return self.storage.query(addr, inum)


class Translator(translator.Translator):

    class CfgTranslator(Cfg):

        def __init__(self, translator):

            self.translator = translator
            self.insn_list = []

        def get_insn(self, addr):

            return self.translator.process_insn(addr)

        def process_node(self, bb):

            for insn in bb.insn_list: self.insn_list.append(insn)
            return True

    def __init__(self, arch, reader = None, storage = None):

        self.reader = reader
        self.storage = storage

        translator.Translator.__init__(self, arch)

    def process_insn(self, addr):

        ret = []

        try: 

            # query already translated IR instructions for this address
            return self.storage.query(addr)

        except KeyError:

            # read instruction bytes from memory
            data = self.reader.read_insn(addr)
            if data is None:

                raise(Exception('Unable to read instruction ' + hex(addr)))        

            # translate to REIL
            ret = self.to_reil(data, addr = addr)

        # save to storage
        for insn in ret: self.storage.store(insn)

        return map(lambda insn: Insn(insn), ret)

    def process_bb(self, addr):

        cfg = self.CfgTranslator(self)
        bb = cfg.get_bb(addr)

        return bb.insn_list

    def process_func(self, addr):

        cfg = self.CfgTranslator(self)
        cfg.traverse(addr)

        return cfg.insn_list
#
# EoF
#