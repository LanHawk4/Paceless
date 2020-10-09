import rsrcfork
from bare68k.consts import *
import bare68k.api.traps as traps
from macmemory import MacMemory

UNIMPLEMENTED_TRAP = 0xA89F
UNIMPL_TRAP_ADDR   = 0xFFFF0000

TRAP_TABLE = {
    # trap #    trap name               method name         trap address  params
    0xA01B : ("_SetZone",               'dummy_trap',       0xFFF30000),
    0xA029 : ("_HLock",                 'dummy_trap',       0xFFF30004),
    0xA02E : ("_BlockMove",             'block_copy',       0xFFF30008),
    0xA055 : ("_StripAddress",          'dummy_trap',       0xFFF3000C),
    0xA064 : ("_MoveHHi",               'dummy_trap',       0xFFF30010),
    0xA0AD : ("_GestaltDispatch",       'dummy_trap',       0xFFF30014),
    0xA0BD : ("_CacheFlush",            'dummy_trap',       0xFFF30018),
    0xA11A : ("_GetZone",               'dummy_trap',       0xFFF3001C),
    0xA122 : ("_NewHandle",             'new_handle',       0xFFF30020),
    0xA128 : ("_RecoverHandle",         'recover_handle',   0xFFF30024),
    0xA162 : ("_PurgeSpace",            'dummy_trap',       0xFFF30028),
    0xA1AD : ("_Gestalt",               'gestalt',          0xFFF3002C),
    0xA025 : ("_GetHandleSize",         'get_handle_size',  0xFFF30030),
    0xA31E : ("_NewPtrClear",           'new_ptr_clear',    0xFFF30034),
    0xA322 : ("_NewHandleClear",        'new_handle_clear', 0xFFF30038),
    0xA346 : ("_GetOSTrapAddress",      'get_trap_addr',    0xFFF3003C),
    0xA746 : ("_GetToolTrapAddress",    'get_trap_addr',    0xFFF30040),
    0xA994 : ("_CurResFile",            'dummy_trap',       0xFFF30044),
    0xA9A0 : ("_GetResource",           'get_resource',     0xFFF30048, 'W', 'L'),
}

def fourcc_to_bytes(fourcc):
    res = bytearray()
    for i in range(4):
        res.append((fourcc >> (24 - i * 8)) & 0xFF)
    return bytes(res)

def sign_extend(value, bits):
    sign_bit = 1 << (bits - 1)
    return (value & (sign_bit - 1)) - (value & sign_bit)

class InvalidTrap(Exception):
    def __init__(self, msg):
        self._msg =  msg

class MacTraps:
    def __init__(self, rt, rf_path):
        self._rt = rt # bare68k runtime object
        self._rf = rsrcfork.open(rf_path) # rsrcfork object
        self._last_trap = UNIMPLEMENTED_TRAP
        self._args = []
        self._mm = MacMemory(rt)
        self._register_traps()

    def _register_traps(self):
        ''' Register supported A-Traps with bare68k '''
        for key in TRAP_TABLE.keys():
            traps.trap_enable(key)

    def _init_memory_manager(self):
        ''' Initialize emulated memory manager '''
        pass

    def get_trap_name(self, trap_num):
        ''' Returns human readable name for trap_num to be used with disassembler '''
        if trap_num not in TRAP_TABLE:
            raise InvalidTrap("Unsupported trap %X" % trap_num)
        return TRAP_TABLE[trap_num][0]

    def atrap_handler(self, event):
        ''' Main dispatcher that intercepts and emulates Macintosh traps '''
        trap_num = event.value
        if trap_num not in TRAP_TABLE:
            raise InvalidTrap("Unsupported trap %X" % trap_num)
        self._last_trap = trap_num
        trap_info = TRAP_TABLE[trap_num]
        print("%s trap invoked!" % trap_info[0])
        if len(trap_info) > 3:
            #print("...has %d stack params!" % (len(trap_info) - 3))
            sp = self._rt.get_cpu().r_sp()
            par_size = 0
            for i in range(len(trap_info) - 3):
                if trap_info[i + 3] == 'L':
                    self._args.insert(0, self._rt.get_mem().r32(sp))
                    sp += 4
                    par_size += 4
                else:
                    self._args.insert(0, self._rt.get_mem().r16(sp))
                    sp += 2
                    par_size += 2
            self._rt.get_cpu().w_sp(sp) # remove params from 68k stack
        getattr(self, trap_info[1])()

    def dummy_trap(self):
        print("Do nothing for this trap")

    def recover_handle(self): # param: A0 - ptr, result: A0 - handle
        h = self._mm.recover_handle(self._rt.get_cpu().r_reg(M68K_REG_A0))
        self._rt.get_cpu().w_reg(M68K_REG_A0, h)

    def get_handle_size(self):
        sz = self._mm.get_handle_size(self._rt.get_cpu().r_reg(M68K_REG_A0))
        self._rt.get_cpu().w_reg(M68K_REG_D0, sz)

    def new_handle(self):
        sz = self._rt.get_cpu().r_reg(M68K_REG_D0)
        print("NewHandle size %X" % sz)
        self._rt.get_cpu().w_reg(M68K_REG_A0, self._mm.new_handle(sz))

    def new_ptr_clear(self):
        sz = self._rt.get_cpu().r_reg(M68K_REG_D0)
        print("NewPtr size %X" % sz)
        new_ptr = self._mm.alloc_mem(sz)
        for i in range(sz):
            self._rt.get_mem().w8(new_ptr + i, 0)
        self._rt.get_cpu().w_reg(M68K_REG_A0, new_ptr)

    def new_handle_clear(self):
        sz = self._rt.get_cpu().r_reg(M68K_REG_D0)
        print("NewHandle size %X" % sz)
        self._rt.get_cpu().w_reg(M68K_REG_A0, self._mm.new_handle(sz, zero=True))

    def get_trap_addr(self):
        trap_num = (self._rt.get_cpu().r_reg(M68K_REG_D0)) & 0xFFFF
        print("Trap num %X" % trap_num)
        if trap_num == UNIMPLEMENTED_TRAP or trap_num not in TRAP_TABLE:
            self._rt.get_cpu().w_reg(M68K_REG_A0, UNIMPL_TRAP_ADDR)
        else:
            self._rt.get_cpu().w_reg(M68K_REG_A0, TRAP_TABLE[trap_num][2])

    def block_copy(self):
        src = self._rt.get_cpu().r_reg(M68K_REG_A0)
        dst = self._rt.get_cpu().r_reg(M68K_REG_A1)
        cnt = self._rt.get_cpu().r_reg(M68K_REG_D0)
        if dst >= (src + cnt) and dst < (src + cnt):
            print("WARNING! _BlockMove source and destination regions overlap!")
        for i in range(cnt):
            self._rt.get_mem().w8(dst + i, self._rt.get_mem().r8(src + i))
        self._rt.get_cpu().w_reg(M68K_REG_D0, 0) # return noErr

    def gestalt(self):
        sel = fourcc_to_bytes(self._rt.get_cpu().r_reg(M68K_REG_D0))
        print("Gestalt called, selector='%s'" % sel.decode())
        self._rt.get_cpu().w_reg(M68K_REG_A0, 0xDEADBEEF)

    def get_resource(self):
        res_type = fourcc_to_bytes(self._args[0])
        res_id   = sign_extend(self._args[1], 16)
        print("Res type = %s" % res_type.decode())
        print("Res ID = %d" % res_id)

        if res_type not in self._rf or res_id not in self._rf[res_type]:
            print("Missing resource %s, ID=%X!" % (res_type.decode(), res_id))

        res_info = self._rf[res_type][res_id]
        res_h    = self._mm.new_handle(res_info.length)
        res_ptr  = self._rt.get_mem().r32(res_h)
        print("res_ptr=%X" % res_ptr)
        print("res_info.length=%X" % res_info.length)
        for i in range(res_info.length):
            self._rt.get_mem().w8(res_ptr + i, res_info.data_raw[i])

        sp = self._rt.get_cpu().r_sp()
        self._rt.get_mem().w32(sp, res_h)
