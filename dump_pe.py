import struct
dll_path = r"C:\Users\Possum\AppData\Local\Programs\RinkSide\NHL Legacy\rexruntime.dll"
data = open(dll_path, "rb").read()
pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
num_sections = struct.unpack_from("<H", data, pe_offset + 6)[0]
opt_header_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
sect_offset = pe_offset + 24 + opt_header_size
sections = []
for i in range(num_sections):
    s_name, s_vsize, s_va, s_rawsize, s_rawptr = struct.unpack_from("<8sIIII", data, sect_offset + i * 40)
    name = s_name.decode("latin1", errors="ignore").strip("\x00")
    print(i, name, hex(s_va), hex(s_vsize))
    sections.append((name, s_va, s_vsize, s_rawsize, s_rawptr))
