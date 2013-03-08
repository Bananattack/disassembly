#!/usr/bin/env python
import glob
import os
import re

os.chdir(os.path.dirname(os.path.abspath(__file__)))

def match_bank_number(line):
    comment = re.match(r'//.*\(memory page ([0-9])*\)', line)
    return comment.group(1) if comment else None

def match_directive(line):
    directive = re.match(r'\s*\.([A-Za-z]*)\s*($|\s+([^/]*)(//(.*))?)', line)
    if directive:
        cmd = directive.group(1).lower()
        arg = directive.group(3).strip() or ''
        comment = directive.group(5)
        return (cmd, arg, comment.strip() if comment else None)
    return None

def match_instruction(line):
    instruction = re.match(r'\s*([A-Za-z][A-Za-z][A-Za-z])($|\s+([^/]*)\s*(//(.*))?|([-+])*\s*(//(.*))?)', line)
    if instruction:
        cmd = instruction.group(1).lower()
        arg = instruction.group(3) or instruction.group(6) or ''
        comment = instruction.group(5) or instruction.group(7)
        return (cmd, arg.strip(), comment.strip() if comment else None)
    return None

def hex_reference_or_value(value, bankname, references):
    if value in references:
        if value < 0xC000:
            return bankname + '_{:04X}'.format(value)
        else:
            return 'game_engine_page_{:04X}'.format(value)
    else:
        return hex(value)

def convert_number(s, bankname, references):
    literal = re.match('(([0-9]+)|([\$L]([0-9A-Fa-f]+))|(%([0-9A-Fa-f]+))|([_A-Za-z][^,]*))', s)
    if not literal:
        print(s)
    term = (literal.group(2) or
        (hex_reference_or_value(int(literal.group(4), 16), bankname, references) if literal.group(4) else None) or
        ('0b' + literal.group(6) if literal.group(6) else None) or
        (literal.group(7).lower() if literal.group(7) else None))
    return term

def convert_arg(filename, lineno, arg, bankname, references, anonymous_label_index):
    if not arg:
        return ''

    def extract_memory_term(match):
        if match.group(3):
            return hex_reference_or_value(int(match.group(3), 16), bankname, references)
        elif match.group(4):
            return match.group(4).lower()
        return None

    immediate = re.match(r'^#(([0-9]+)|([\$L]([0-9A-Fa-f]+))|(%([0-9A-Fa-f]+))|([_A-Za-z][^,]*))$', arg)
    direct = re.match(r'^(([\$L]([0-9A-Fa-f]+))|([_A-Za-z][^,]*))$', arg)
    indexed = re.match(r'^(([\$L]([0-9A-Fa-f]+))|([_A-Za-z][^,]*)),\s*([xyXY])$', arg)
    indirect = re.match(r'^\((([\$L]([0-9A-Fa-f]+))|([_A-Za-z][^,]*))\)$', arg)
    indirect_indexed_by_y = re.match(r'^\((([\$L]([0-9A-Fa-f]+))|([_A-Za-z][^,]*))\),\s*[yY]$', arg)
    relative_label = re.match(r'^(-+)|(\++)$', arg)
    if immediate:
        return convert_number(immediate.group(1), bankname, references)
    elif direct:
        term = extract_memory_term(direct)
        return '[' + term + ']'
    elif indexed:
        term = extract_memory_term(indexed)
        index = indexed.group(5).lower()
        return '[' + term + ':' + index + ']'
    elif indirect:
        term = extract_memory_term(indirect)
        return '[[' + term + ']]'
    elif indirect_indexed_by_y:
        term = extract_memory_term(indirect_indexed_by_y)
        return '[[' + term + ']:y]'
    elif relative_label:
        if relative_label.group(1):
            label_index = anonymous_label_index - relative_label.group(1).count('-')
        elif relative_label.group(2):
            label_index = anonymous_label_index + relative_label.group(2).count('+') - 1
        return '[_{:04X}]'.format(label_index)
    else:
        raise Exception(filename + ':' + str(lineno) + ': unhandled arg pattern "' + arg + '"')


NullaryInstructionConversions = {
    'inx': 'x++',
    'iny': 'y++',
    'dex': 'x--',
    'dey': 'y--',
    'asl': 'a = a << 1',
    'lsr': 'a = a >> 1',
    'rol': 'a = a <<< 1',
    'ror': 'a = a >>> 1',
    'rts': 'return',
    'rti': 'resume',
    'clc': 'carry = 0',
    'sec': 'carry = 1',
    'cli': 'interrupt = 0',
    'sei': 'interrupt = 1',
    'tax': 'x = a',
    'tay': 'y = a',
    'tsx': 'x = s',
    'txa': 'a = x',
    'txs': 's = x',
    'tya': 'a = y',
    'php': 'push p',
    'pha': 'push a',
    'pla': 'a = pop',
    'plp': 'p = pop',
    'cld': 'decimal = 0',
    'sed': 'decimal = 1',
    'nop': 'nop',
}
UnaryInstructionConversions = {
    'lda': 'a = {0}',
    'ldx': 'x = {0}',
    'ldy': 'y = {0}',
    'sta': '{0} = a',
    'stx': '{0} = x',
    'sty': '{0} = y',
    'adc': 'a = a +# {0}',
    'sbc': 'a = a -# {0}',
    'and': 'a = a & {0}',
    'ora': 'a = a | {0}',
    'eor': 'a = a ^ {0}',
    'inc': '{0}++',
    'dec': '{0}--',
    'asl': '{0} = {0} << 1',
    'lsr': '{0} = {0} >> 1',
    'rol': '{0} = {0} <<< 1',
    'ror': '{0} = {0} >>> 1',
    'cmp': 'compare a to {0}',
    'cpx': 'compare x to {0}',
    'cpy': 'compare y to {0}',
    'bit': 'compare a & {0}',
}
BranchInstructionConversions = {
    'jmp': 'goto {0}',
    'jsr': 'call {0}',
    'bcc': 'goto {0} when ~carry',
    'bcs': 'goto {0} when carry',
    'bpl': 'goto {0} when ~negative',
    'bmi': 'goto {0} when negative',
    'bne': 'goto {0} when ~zero',
    'beq': 'goto {0} when zero',
    'bvc': 'goto {0} when ~overflow',
    'bvs': 'goto {0} when overflow',
}

def convert_instruction(filename, lineno, cmd, arg):
    nullary = NullaryInstructionConversions.get(cmd)
    unary = UnaryInstructionConversions.get(cmd)
    branch = BranchInstructionConversions.get(cmd)

    if nullary and not arg:
        return nullary
    elif unary and arg:
        return unary.format(arg)
    elif branch and arg:
        return branch.format(arg[1:-1])
    else:
        raise Exception(filename + ':' + str(lineno) + ': unhandled command "' + cmd
            + '" with ' + ('argument "' + arg + '"' if arg else 'no argument'))

def tidy_line(line, bankname, references = None):
    line = line.replace(';', '//').replace('*\t', '*').replace('\t', '    ').replace('\n', '')
    label = re.match(r'L([8-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]):\s*(.*)', line)
    if label:
        line = label.group(2)
        if not references or int(label.group(1), 16) in references:
            label = bankname + '_{:04X}'.format(int(label.group(1), 16))
        else:
            label = None
    return (line, label)

def convert_to_underscores(name):
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def scan():
    global_refs = []
    contexts = {}
    global_labels = set()

    def match_address(s):
        address = re.match(r'([\$L]([8-9A-Fa-f][0-9A-Fa-f]*)|\(\$([0-9A-Fa-f]*)\))', s)
        if address:
            return int(address.group(2) or address.group(3), 16)
        return None

    for filename in glob.glob('Metroid*.txt'):
        anonymous_label_index = 0

        context = {
            'filename': filename,
            'outname': os.path.splitext(filename)[0] + '.wiz',
            'bank_name': convert_to_underscores(os.path.splitext(os.path.basename(filename))[0][7:]),
            'references': [],
            'labels': set()
        }
        contexts[filename] = context

        for line in open(filename):
            line, label = tidy_line(line, context['bank_name'])
            bank_number = match_bank_number(line)
            directive = match_directive(line)
            instruction = match_instruction(line)
            if label:
                address = int(label.split('_page_')[1], 16)
                if address >= 0x8000 and address < 0xC000:
                    context['labels'].add(address)
                if address >= 0xC000:
                    print(hex(address))
                    global_labels.add(address)

            if bank_number:
                context['bank_number'] = bank_number
            elif directive:
                cmd, arg, comment = directive
                if cmd == 'word':
                    for item in arg.split(','):
                        address = match_address(item)
                        if address:
                            if address >= 0x8000 and address < 0xC000:
                                context['references'].append(address)
                            if address >= 0xC000:
                                global_refs.append(address)
            elif instruction:
                cmd, arg, comment = instruction
                address = match_address(arg)
                if address:
                    if address >= 0x8000 and address < 0xC000:
                        context['references'].append(address)
                    if address >= 0xC000:
                        global_refs.append(address)

    #print([hex(ref) for ref in global_refs])
    print(0xfc65 in global_refs)
    global_refs = [ref for ref in global_refs if ref in global_labels]
    for name, context in contexts.items():
        context['references'] = [ref for ref in context['references'] if ref in context['labels']] + global_refs
    #print(0xF global_labels)
    print(0xfc65 in global_refs)
    return contexts

def translate(contexts):
    for name, context in contexts.items():
        filename = context['filename']
        bankname = context['bank_name']
        references = context['references']
        out = open(context['outname'], 'w')
        anonymous_label_index = 0

        lineno = 0
        for line in open(filename):
            lineno += 1
            result = []

            line, label = tidy_line(line, bankname, references)
            if label:
                result.append('def ' + label + ':')

            label_decl = re.match(r'^\s*([A-Za-z0-9_]+):(.*)', line)
            if label_decl:
                result.append('def ' + label_decl.group(1).lower() + ':')
                line = label_decl.group(2)

            if line.startswith('*'):
                result.append('def _{:04X}:'.format(anonymous_label_index))
                anonymous_label_index += 1
                line = line[1:]

            directive = match_directive(line)
            instruction = match_instruction(line)
            if directive:
                cmd, arg, comment = directive
                if cmd == 'org':
                    if comment: result.append('    //' + comment)
                    result.append('in ' + context['bank_name'] + ', ' + arg.replace('$', '0x') + ':'
                        + (' do' if bankname != 'game_engine_page' else '')
                    )
                        
                elif cmd == 'byte':
                    if comment: result.append('    //' + comment)
                    items = []
                    for item in arg.split(','):
                        items.append(convert_number(item.strip(), bankname, references))
                    result.append('    byte: ' + ', '.join(items))
                elif cmd == 'word':
                    if comment: result.append('    //' + comment)
                    items = []
                    for item in arg.split(','):
                        items.append(convert_number(item.strip(), bankname, references))
                    result.append('    word: ' + ', '.join(items))
                elif cmd == 'alias':
                    if comment: result.append('    //' + comment)
                    result.append('    let ' + arg.split()[0].lower() + ' = ' + arg.split()[1].replace('$', '0x').replace('%', '0b'))
                elif cmd == 'include':
                    pass
                else:
                    raise Exception(filename + ':' + str(lineno) + ': unhandled directive "' + cmd + '"')
            elif instruction:
                cmd, arg, comment = instruction
                if comment: result.append('    //' + comment)
                arg = convert_arg(filename, lineno, arg, bankname, references, anonymous_label_index)
                result.append('    ' + convert_instruction(filename, lineno, cmd, arg))
            else:
                result.append(line)

            out.write('\n'.join(result) + '\n')
        if bankname != 'game_engine_page' and bankname != 'defines':
            out.write('end\n')

    out = open('Metroid.wiz', 'w')
    out.write('let K = 1024\n\n')
    banks = []
    out.write('bank header : rom * 16\n')
    for name, context in contexts.items():
        if context.get('bank_number'):
            banks.append((context['bank_number'], context['bank_name']))
    for bank in sorted(banks):
        out.write('bank ' + bank[1] + ' : rom * 16 * K\n')
    out.write('\n')
    out.write('''
in header, 0x00:
    do
        let mirroring = 1
        let battery = 0
        let fourscreen = 0
        let mapper = 1

        // 0..3: "NES" followed by MS-DOS end-of-file marker.
        byte * 4: "NES", 0x1A
        // 4: Number of 16K PRG ROM banks
        byte: 8
        // 5: Number of 8K CHR ROM banks
        byte: 0
        // 6: The "Flags 6" byte, skip the 'trainer' flag for now.
        byte: (mirroring) | (battery << 1) | (fourscreen << 3) | ((mapper & 0xF) << 4)
        // 7: The "Flags 7" byte, just the mapper part though.
        byte: (mapper >> 4)
        // 8: Number of 8K PRG RAM banks -- for now just write a 0, which implies 8KB PRG RAM at most.
        byte: 0
        // 9..15: Ignore other flag fields. Zero-pad this header to 16 bytes.
        byte: 0, 0, 0, 0, 0, 0, 0
    end
    \n''')

    for name, context in contexts.items():
        out.write('include "' + context['outname'] + '"\n')

translate(scan())