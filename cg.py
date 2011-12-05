#!/usr/bin/env python

'''
TODO
- implement rest of costs/calls
- implement jumps
- source line annotation
- use addr2line on objects
- choose events to display
- inline functions

Docs:
- Callgrind Format Spec:  http://valgrind.org/docs/manual/cl-format.html

'''

import sys

MAX_DEPTH = 16

FUNCTION_TERMINALS = set(['regfree()', 'regcomp()', 'regexec()', '__umodti3()', "__umodti3'2",
                          'malloc()', 'calloc()', 'realloc()', 'free()',
                          'memcpy()', 'memset()',
                          ])

IGNORE_STUBS = True
VERBOSE = False

CALLGRIND_FIELDS = {
     'ob'   : 'object',
     'fl'   : 'filename',
     'fi'   : 'filename', # 'inline' function
     'fe'   : 'filename', # 'exit' inline function
     'fn'   : 'function',
     'jump' : 'jump',
     'jcnd' : 'jump (conditional)',
     'alls' : 'calls',  # actually calls, but being sneaky here...
     }

POINTER_MAPPING = {
    'ob'  : 'ob',
    'cob' : 'ob',

    'fl'  : 'fl',
    'cfl' : 'fl',
    'fi'  : 'fl',

    'fn'  : 'fn',
    'fe'  : 'fn',
    'cfn' : 'fn',

    'jump' : 'jump',
    'jcnd' : 'jump',
    }

def base_context():
    return {"object"   : "???",
            "filename" : "???",
            "function" : "???",
            "line"     : -1,
            "previous" : None,
            }

def context():
    c = base_context()
    c['costs'] = []
    c['calls'] = []
    c['jumps'] = []
    return c

def call_context():
    c = base_context()
    c['calls'] = []
    return c

class CallgrindAnnotate():
    def __init__(self, path):
        self.path = path
        self.line_num = 0
        self.NIZZLE = 0

    def error(self, msg):
        raise SystemExit("%s:%d Error %s" % (self.path, self.line_num + 1, msg))

    def new_context(self):
        if self.contexts:
            self.functions[self.context['function']] = self.context

            # Copy the existing context and clear it
            self.context = dict(self.context)
            self.context['function'] = '???'
            self.context['costs'] = []
            self.context['calls'] = []
        else:
            self.context = context()

        self.call_context = None
        self.contexts.append(self.context)

    def lookup(self, mapping_type, key):
        v = self.pointers[mapping_type].get(key, key)
        # LAME hack for functions with contexts
        if len(v) == 2 and type(v) != str:
            return v[0]
        return v

    def walk_call_stack(self, context, prefix = ""):
        function = self.lookup('fn', context['function'])
        filename = self.lookup('fl', context['filename'])
        obj      = self.lookup('ob', context['object'])

        line = context['line']
        calls = context['calls']
        costs = context['costs']

        function_pieces = []

        if IGNORE_STUBS:
            if 'stub ' in function or 'dyld_stub' in function:
                return

        if ' ' not in function and "'" not in function:
            function += '()'

        function_pieces = []

        total_cost = 0

        if filename != '???':
            function_pieces.append(filename)

            if line >= 0:
                function_pieces.append(':: %d' % line)

            if costs and len(costs) > 0:
                first_line = costs[0][0]
                if first_line > 0:
                    function_pieces.append('[line %s]' % first_line)

        if costs and len(costs) > 0:
            # costs are in the format of:
            # [line, [cost...]]
            total_cost = sum([i[1][0] for i in costs])

        if filename == '???':
            #if obj != '???' and not self.metadata['cmd'].startswith(obj):
            if obj != '???':
                function_pieces.append('[%s]' % obj)

        base = "%8d | %s + %s" % (total_cost, prefix, function)
        print "%-30s %s" % (base, ' '.join(function_pieces))

        if function in FUNCTION_TERMINALS:
            #print "at terminal"
            return

        prefix += ' ' * 2

        if len(prefix) > MAX_DEPTH:
            print "ABORT"
            return

        prev_function = None

        for call in calls:
            function = call['function']
            function_context = self.functions.get(function)
            if function_context:
                function_name = function_context['function']
                if VERBOSE:
                    print "Function call: %s => %s" % (function, function_name)
                if function_context != context and function_name != prev_function:
                    prev_function = function_name
                    self.walk_call_stack(function_context, prefix)
            else:
                print "Unknown function: %s" % function
                #import pdb; pdb.set_trace()

    def parse_costs(self, current, s):
        pieces = s.split()
        values = []
        previous = current['previous']

        if not self.events:
            self.events = self.metadata['events'].split()

        if len(pieces) < len(self.events) + 1:
            # Callgrind compression allows dropping of trailing "0" costs
            pieces += ["0"] * (len(self.events) + 1 - len(pieces))

        for (index, value) in enumerate(pieces):
            first = value[0]
            if not previous or (index >= len(previous)):
                p = value
            else:
                p = previous[index]

            if first in ['+', '-']:
                # Delta compressed value
                v = p + int(value)
            elif first == '*':
                # "Same" value
                v = p
            else:
                v = int(value)

            values.append(v)

        line_number = values[0]
        costs = values[1:]

        return (line_number, costs, values)

    def find_function(self, name):
        function = self.functions.get(name)
        if function:
            return function

        all_functions = self.pointers['fn']

        for (k, v) in all_functions.iteritems():
            c = None

            if v == name:
                function = self.functions.get(k)
                if function:
                    return function
                else:
                    print "Function %s not found" % name
                    break
        return None

    def get_line(self):
        line = self.f.readline()

        if not line:
            # EOF
            return False

        self.line_num += 1
        self.line = line.strip()

        if not self.line:
            # Blank line
            if self.started:
                #print "New context @ %d" % self.line_num
                self.new_context()

            # Again
            return self.get_line()

        if VERBOSE:
            print "%4d : %s" % (self.line_num, self.line)

        return True

    def annotate(self):
        self.f = open(self.path, "r")

        self.started = False

        self.metadata = {}
        self.events = []

        self.contexts = []
        self.functions = {}

        self.new_context()
        self.pointers = {'ob' : {},
                         'fn' : {},
                         'fl' : {},
                         'jump' : {},
                         }

        while self.get_line():
            s = self.line

            first_equals = s.find('=')
            first_colon = s.find(':')
            first_space = s.find(' ')

            if first_colon >= 0 and (first_equals < 0 or first_colon < first_equals):
                # metadata
                pieces = s.split(": ")
                if len(pieces) >= 2:
                    key = pieces[0]
                    value = ': '.join(pieces[1:])
                    value = value.strip()
                    self.metadata[key] = value
                    print "%10s: %s" % (key, value)

            else:
                c = self.context
                call = False

                if first_equals >= 0 and (first_space == -1 or first_equals < first_space):
                    # context info
                    self.started = True
                    key = s[:first_equals]
                    rest = s[first_equals + 1:]

                    call = (key[0] == 'c')
                    if call:
                        # e.g. cob, cfl, cfn...
                        key = key[1:] # drop the leading 'c'
                        if not self.call_context:
                            self.call_context = call_context()
                            self.context['calls'].append(self.call_context)
                            #current_context = self.call_context
                        c = self.call_context

                    field = CALLGRIND_FIELDS.get(key)
                    if not field:
                        self.error("key [%s] unknown | %s" % (key, rest))

                    pieces = rest.split()

                    #if self.NIZZLE == 1:
                    #    import pdb; pdb.set_trace()
                    #    print "hello"
                    #
                    #if 'cfn=(798)' in self.line:
                    #    self.NIZZLE = 1

                    if call and key in ['alls']:
                        rest = pieces

                        # Second line of call (costs)
                        self.get_line()
                        s = self.line

                        pieces = s.split()
                        values = []

                        for i in pieces:
                            if i == '*':
                                values.append(1337)
                            else:
                                values.append(int(i))

                        self.call_context['calls'] += values
                        self.context['costs'].append([values[0], values[1:]])

                        self.call_context = None
                        #import pdb; pdb.set_trace()

                        #self.context.costs.append()

                    elif len(pieces) >= 2:
                        first = pieces[0]
                        mapping = POINTER_MAPPING.get(key)
                        if not mapping:
                            self.error("Bad key: %s" % (key))

                        pointers = self.pointers[mapping]
                        if VERBOSE:
                            print "Found pointer [%s] => %s" % (mapping, key)
                        #import pdb; pdb.set_trace()

                        if first[0] == '(' and first[-1] == ')':
                            pointer = first
                            rest = pointer

                            foo = ' '.join(pieces[1:])
                            #pointers[pointer] = (foo, current_context)
                            pointers[pointer] = foo#, self.context)

                        else:
                            pointers[rest] = (rest, self.context)

                        if VERBOSE:
                            print "%6s => %12s => %s" % (key, field, rest)

                    #if not call and key == 'fn':
                    #    self.functions[rest] = self.context

                    if field and field != 'calls':
                        #if '13080' in rest:
                        #    import pdb; pdb.set_trace()

                        c[field] = rest

                else:
                    (line_number, costs, values) = self.parse_costs(self.context, s)

                    self.context['costs'].append([line_number, costs])
                    self.context['previous'] = values

                    #else:
                    #    print "costs[%s] => %s" % (self.current_pointer, self.current_spec.costs[self.current_pointer])

        if self.contexts:
            # Drop the final context if empty
            last = self.contexts[-1]
            if not last['calls'] and not last['costs']:
                self.contexts = self.contexts[:-1]

        if VERBOSE:
            for (i, context) in enumerate(self.contexts):
                print "-" * 80
                print "Context %d" % (i + 1)
                import pprint; pprint.pprint(context)

            print "-" * 80

            for (function, context) in self.functions.iteritems():
                print "%15s: %s" % (function, context['costs'])

            print "-" * 80

        print "-" * 80
        #TOP_FUNCTION = '(below main)'
        TOP_FUNCTION = 'main'
        top = self.find_function(TOP_FUNCTION)
        if not top:
            print "WARNING: Did not find '%s' => using first context" % TOP_FUNCTION
            top = self.contexts[0]

        print "Call stack:"
        self.walk_call_stack(top)
        print "-" * 80

        if VERBOSE:
            print "Done: %d lines" % (self.line_num)

        self.f.close()

if __name__ == "__main__":
    args = sys.argv

    pdb = False

    if '--pdb' in args:
        args.remove('--pdb')
        pdb = True

    if '--verbose' in args:
        args.remove('--verbose')
        VERBOSE = True

    if len(args) != 2:
        raise SystemExit("Usage: %s FILE" % args[0])

    f = sys.argv[1]
    try:
        CallgrindAnnotate(f).annotate()
    except BaseException, e:
        if pdb:
            import pdb, sys
            print "-" * 80
            print "Caught Exception: %s" % e
            print "-" * 80
            e, m, tb = sys.exc_info()
            pdb.post_mortem(tb)
        else:
            raise
