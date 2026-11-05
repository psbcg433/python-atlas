# Phase 1 Cheat Sheet

[← Previous](project-log-analyzer.md) · [Index](README.md)

One-stop revision tables for Phase 1. Every row is one line; every Result cell was produced by running the Example on CPython 3.15. Each group links to the unit that explains it. Examples that mutate state start from the variables named above their table.

## Contents

- [Built-in types at a glance](#built-in-types-at-a-glance)
- [Numbers, booleans and None](#numbers-booleans-and-none)
- [Strings](#strings)
- [Bytes and byte arrays](#bytes-and-byte-arrays)
- [Sequences, lists, tuples, ranges](#sequences-lists-tuples-ranges)
- [Dictionaries](#dictionaries)
- [Sets and frozen sets](#sets-and-frozen-sets)
- [The collections module](#the-collections-module)
- [Copying](#copying)
- [Operators and syntax forms](#operators-and-syntax-forms)
- [Built-in functions](#built-in-functions)
- [Functions and parameters](#functions-and-parameters)
- [Scope rules](#scope-rules)
- [Decorators, functools, operator](#decorators-functools-operator)
- [Iterators, generators, itertools](#iterators-generators-itertools)
- [Exceptions and context managers](#exceptions-and-context-managers)

## Built-in types at a glance

Explained in [Unit 1.3](unit-1-3-numeric-and-boolean-data-types.md).

| Type | Literal | Mutable | JS nearest |
| --- | --- | --- | --- |
| `int` | `42`, `0xFF`, `1_000` | No | `number` / `BigInt` |
| `float` | `3.14`, `1e-3` | No | `number` |
| `complex` | `2+3j` | No | — |
| `bool` | `True`, `False` | No | `boolean` |
| `NoneType` | `None` | No | `null` / `undefined` |
| `str` | `'hi'`, `f'{x}'` | No | `string` |
| `bytes` | `b'hi'` | No | `Uint8Array` (frozen) |
| `bytearray` | `bytearray(b'hi')` | Yes | `Uint8Array` |
| `list` | `[1, 2]` | Yes | `Array` |
| `tuple` | `(1, 2)`, `1,` | No | frozen `Array` |
| `range` | `range(5)` | No | — |
| `dict` | `{'a': 1}` | Yes | `Map` / object |
| `set` | `{1, 2}` | Yes | `Set` |
| `frozenset` | `frozenset({1})` | No | — |

Hashable (usable as a dict key or set member): the immutable types, and tuples whose items are all hashable. Mutable containers are unhashable.

## Numbers, booleans and None

Explained in [Unit 1.3](unit-1-3-numeric-and-boolean-data-types.md).

### Arithmetic

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `/` | True division, always float | `7 / 2` | `3.5` |
| `//` | Floor division | `-7 // 2` | `-4` |
| `%` | Modulo, sign of divisor | `-7 % 2` | `1` |
| `**` | Power | `2 ** 100 > 10 ** 30` | `True` |
| `divmod` | Quotient and remainder | `divmod(17, 5)` | `(3, 2)` |
| `round` | Round half to even | `(round(2.5), round(3.5))` | `(2, 4)` |
| `round(x, n)` | Round to n digits | `round(3.14159, 2)` | `3.14` |
| `abs` | Absolute value | `abs(-4.5)` | `4.5` |
| `pow(b, e, m)` | Modular power | `pow(3, 4, 5)` | `1` |
| `math.isclose` | Float comparison | `math.isclose(0.1 + 0.2, 0.3)` | `True` |
| `math.floor` | Round down to int | `math.floor(-2.5)` | `-3` |
| `math.ceil` | Round up to int | `math.ceil(2.1)` | `3` |
| `math.trunc` | Toward zero | `math.trunc(-2.7)` | `-2` |

### int and float methods

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `bit_length` | Bits needed | `(255).bit_length()` | `8` |
| `bit_count` | Number of 1 bits | `(255).bit_count()` | `8` |
| `to_bytes` | Int to bytes | `(258).to_bytes(2, 'big')` | `b'\x01\x02'` |
| `int.from_bytes` | Bytes to int | `int.from_bytes(b'\x01\x02', 'big')` | `258` |
| `int(s, base)` | Parse in a base | `int('ff', 16)` | `255` |
| `is_integer` | Whole-number float? | `(2.0).is_integer()` | `True` |
| `as_integer_ratio` | Exact fraction | `(0.5).as_integer_ratio()` | `(1, 2)` |
| `float.hex` | Exact hex form | `(0.1).hex()` | `'0x1.999999999999ap-4'` |
| `sys.float_info.max` | Largest float | `sys.float_info.max > 1e308` | `True` |
| `float('inf')` | Infinity | `float('inf') > 10 ** 400` | `True` |
| `float('nan')` | Not equal to itself | `float('nan') == float('nan')` | `False` |

### Decimal, Fraction, complex

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `Decimal(str)` | Exact decimal | `Decimal('0.1') + Decimal('0.2')` | `Decimal('0.3')` |
| `Decimal(float)` | Float's exact value | `Decimal(0.1) == Decimal('0.1')` | `False` |
| `quantize` | Round to a pattern | `Decimal('2.675').quantize(Decimal('0.01'))` | `Decimal('2.68')` |
| `ROUND_HALF_UP` | Rounding mode | `Decimal('2.5').quantize(Decimal('1'), decimal.ROUND_HALF_UP)` | `Decimal('3')` |
| `Fraction` | Exact rational | `Fraction(1, 3) + Fraction(1, 6)` | `Fraction(1, 2)` |
| `limit_denominator` | Nearest simple fraction | `Fraction(0.333).limit_denominator(10)` | `Fraction(1, 3)` |
| `complex` | Real and imaginary | `(2 + 3j) * 1j` | `(-3+2j)` |
| `abs(complex)` | Magnitude | `abs(3 + 4j)` | `5.0` |
| `.real / .imag` | Parts | `(2 + 3j).imag` | `3.0` |

### Booleans, None, truthiness and conversion

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `bool is int` | True == 1 | `True + True` | `2` |
| `isinstance` | bool subclasses int | `isinstance(True, int)` | `True` |
| `is None` | Test for None | `None is None` | `True` |
| `falsy values` | False, None, 0, empty | `[bool(v) for v in (0, '', [], {}, None)]` | `[False, False, False, False, False]` |
| `truthy strings` | Any non-empty str | `bool('False')` | `True` |
| `int(float)` | Truncates | `int(-2.9)` | `-2` |
| `int(str)` | Parse an int | `int(' 42 ')` | `42` |
| `int(bad str)` | Raises | `int('4.2')` | `ValueError` |
| `float(str)` | Parse a float | `float('1e3')` | `1000.0` |
| `str(x)` | To text | `str(3.0)` | `'3.0'` |
| `bool(str)` | Not parsing! | `bool('0')` | `True` |

## Strings

Explained in [Unit 1.4](unit-1-4-text-and-binary-data-types.md).

Strings are immutable: every method returns a new string.

### Changing case

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `upper` | All upper case | `'Straße'.upper()` | `'STRASSE'` |
| `lower` | All lower case | `'HeLLo'.lower()` | `'hello'` |
| `casefold` | Aggressive lower | `'Straße'.casefold()` | `'strasse'` |
| `capitalize` | First char upper | `'hello world'.capitalize()` | `'Hello world'` |
| `title` | Each word capitalised | `'hello world'.title()` | `'Hello World'` |
| `swapcase` | Swap case | `'Hello'.swapcase()` | `'hELLO'` |

### Searching and counting

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `find` | Index or -1 | `'banana'.find('an')` | `1` |
| `rfind` | Last index or -1 | `'banana'.rfind('an')` | `3` |
| `index` | Index or ValueError | `'banana'.index('x')` | `ValueError` |
| `rindex` | Last index or error | `'banana'.rindex('a')` | `5` |
| `count` | Non-overlapping count | `'banana'.count('a')` | `3` |
| `startswith` | Prefix test | `'report.csv'.startswith(('re', 'x'))` | `True` |
| `endswith` | Suffix test | `'report.csv'.endswith('.csv')` | `True` |
| `in` | Substring test | `'nan' in 'banana'` | `True` |

### Testing characters

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `isalpha` | Letters only | `'abc'.isalpha()` | `True` |
| `isalnum` | Letters or digits | `'abc1'.isalnum()` | `True` |
| `isdecimal` | 0-9 style digits | `'²'.isdecimal()` | `False` |
| `isdigit` | Digits incl. ² | `'²'.isdigit()` | `True` |
| `isnumeric` | Digits incl. ½ | `'½'.isnumeric()` | `True` |
| `isascii` | All ASCII | `'café'.isascii()` | `False` |
| `isspace` | Whitespace only | `' \t\n'.isspace()` | `True` |
| `islower` | Cased chars lower | `'abc1'.islower()` | `True` |
| `isupper` | Cased chars upper | `'ABC1'.isupper()` | `True` |
| `istitle` | Title case | `'Hello World'.istitle()` | `True` |
| `isidentifier` | Valid name | `'order_total'.isidentifier()` | `True` |
| `isprintable` | No control chars | `'a\n'.isprintable()` | `False` |

### Splitting and joining

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `split` | Split on separator | `'a,b,,c'.split(',')` | `['a', 'b', '', 'c']` |
| `split()` | Split on whitespace | `'a  b c'.split()` | `['a', 'b', 'c']` |
| `split(sep, n)` | At most n splits | `'a=b=c'.split('=', 1)` | `['a', 'b=c']` |
| `rsplit` | Split from the right | `'a.b.c'.rsplit('.', 1)` | `['a.b', 'c']` |
| `splitlines` | Split on line breaks | `'one\ntwo\r\n'.splitlines()` | `['one', 'two']` |
| `partition` | Head, sep, tail | `'key=value'.partition('=')` | `('key', '=', 'value')` |
| `rpartition` | From the right | `'a/b/c'.rpartition('/')` | `('a/b', '/', 'c')` |
| `join` | Glue an iterable | `', '.join(['a', 'b'])` | `'a, b'` |

### Trimming and padding

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `strip` | Both ends | `'  hi  '.strip()` | `'hi'` |
| `strip(chars)` | A set of chars | `'xxhixx'.strip('x')` | `'hi'` |
| `lstrip` | Left end | `'  hi'.lstrip()` | `'hi'` |
| `rstrip` | Right end | `'hi\n'.rstrip()` | `'hi'` |
| `removeprefix` | Exact prefix | `'v1.2'.removeprefix('v')` | `'1.2'` |
| `removesuffix` | Exact suffix | `'data.csv'.removesuffix('.csv')` | `'data'` |
| `center` | Centre in width | `'hi'.center(6, '*')` | `'**hi**'` |
| `ljust` | Pad right | `'hi'.ljust(5, '.')` | `'hi...'` |
| `rjust` | Pad left | `'hi'.rjust(5, '.')` | `'...hi'` |
| `zfill` | Pad with zeros | `'-42'.zfill(5)` | `'-0042'` |
| `expandtabs` | Tabs to spaces | `'a\tb'.expandtabs(4)` | `'a   b'` |

### Replacing, translating, encoding, formatting

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `replace` | Substitute substrings | `'a-b-c'.replace('-', '+', 1)` | `'a+b-c'` |
| `maketrans` | Build a table | `str.maketrans('ab', 'xy')` | `{97: 120, 98: 121}` |
| `translate` | Map characters | `'abc'.translate(str.maketrans('ab', 'xy'))` | `'xyc'` |
| `encode` | To bytes | `'café'.encode('utf-8')` | `b'caf\xc3\xa9'` |
| `format` | Fill placeholders | `'{} x {}'.format(2, 3)` | `'2 x 3'` |
| `format_map` | Fill from a mapping | `'{name}'.format_map({'name': 'Asha'})` | `'Asha'` |
| `str * n` | Repeat | `'ab' * 3` | `'ababab'` |
| `[::-1]` | Reverse | `'abc'[::-1]` | `'cba'` |

### Format specs

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `=` | Self-documenting | `f'{2 + 3=}'` | `'2 + 3=5'` |
| `<n / >n / ^n` | Align in width | `f'[{"hi":>5}]'` | `'[   hi]'` |
| `fill` | Fill character | `f'{"hi":*^6}'` | `'**hi**'` |
| `,` | Thousands separator | `f'{1234567:,}'` | `'1,234,567'` |
| `_` | Underscore separator | `f'{1234567:_}'` | `'1_234_567'` |
| `.2f` | Fixed decimals | `f'{3.14159:.2f}'` | `'3.14'` |
| `.1%` | Percentage | `f'{0.256:.1%}'` | `'25.6%'` |
| `e` | Scientific | `f'{12345.678:.2e}'` | `'1.23e+04'` |
| `+` | Always show sign | `f'{5:+}'` | `'+5'` |
| `0n` | Zero pad | `f'{7:03}'` | `'007'` |
| `b / o / x` | Binary, octal, hex | `f'{255:b} {255:o} {255:x}'` | `'11111111 377 ff'` |
| `#x` | With prefix | `f'{255:#x}'` | `'0xff'` |
| `!r` | Use repr | `f'{"hi"!r}'` | `"'hi'"` |
| `nested` | Width from a variable | `f'[{"a":>{3}}]'` | `'[  a]'` |

## Bytes and byte arrays

Explained in [Unit 1.4](unit-1-4-text-and-binary-data-types.md).

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `decode` | Bytes to str | `b'caf\xc3\xa9'.decode('utf-8')` | `'café'` |
| `errors=` | Handle bad bytes | `b'\xff'.decode('utf-8', 'replace')` | `'�'` |
| `indexing` | Gives an int | `b'AB'[0]` | `65` |
| `slicing` | Gives bytes | `b'ABC'[:2]` | `b'AB'` |
| `hex` | To hex text | `b'\x01\xff'.hex()` | `'01ff'` |
| `fromhex` | From hex text | `bytes.fromhex('01ff')` | `b'\x01\xff'` |
| `bytes(n)` | n zero bytes | `bytes(3)` | `b'\x00\x00\x00'` |
| `bytearray` | Mutable bytes | `ba[0] = 74` | `ba → bytearray(b'Jam')` |
| `extend` | Append bytes | `ba.extend(b'!')` | `ba → bytearray(b'hi!')` |
| `memoryview` | Zero-copy view | `memoryview(b'abcdef')[2:4].tobytes()` | `b'cd'` |

## Sequences, lists, tuples, ranges

Explained in [Unit 1.5](unit-1-5-collection-data-types-i-lists-tuples-and-ranges.md).

### Common sequence operations

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `x in s` | Membership | `2 in [1, 2, 3]` | `True` |
| `s + t` | Concatenate | `[1] + [2]` | `[1, 2]` |
| `s * n` | Repeat (references!) | `[0] * 3` | `[0, 0, 0]` |
| `s[i]` | Index (negative ok) | `[10, 20, 30][-1]` | `30` |
| `s[i:j:k]` | Slice | `[0, 1, 2, 3, 4][1:4:2]` | `[1, 3]` |
| `len` | Length | `len((1, 2, 3))` | `3` |
| `min / max` | Smallest, largest | `max([3, 9, 4])` | `9` |
| `s.index(x)` | First position | `[5, 6, 5].index(5)` | `0` |
| `s.count(x)` | Occurrences | `[5, 6, 5].count(5)` | `2` |
| `==` | Element-wise compare | `[1, 2] == [1, 2]` | `True` |
| `<` | Lexicographic | `(1, 2) < (1, 3)` | `True` |

### list methods

Examples start from `nums = [3, 1, 2]`.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `append` | Add one item | `nums.append(4)` | `nums → [3, 1, 2, 4]` |
| `extend` | Add many items | `nums.extend([4, 5])` | `nums → [3, 1, 2, 4, 5]` |
| `insert` | Insert at index | `nums.insert(0, 9)` | `nums → [9, 3, 1, 2]` |
| `remove` | Delete first match | `nums.remove(1)` | `nums → [3, 2]` |
| `pop` | Remove, return last | `nums.pop()` | `2; nums → [3, 1]` |
| `pop(i)` | Remove at index | `nums.pop(0)` | `3; nums → [1, 2]` |
| `clear` | Remove all | `nums.clear()` | `nums → []` |
| `index` | Position of value | `nums.index(2)` | `2` |
| `count` | Occurrences | `nums.count(3)` | `1` |
| `sort` | In place, returns None | `nums.sort()` | `nums → [1, 2, 3]` |
| `sort(key=)` | Sort by a key | `words.sort(key=len)` | `words → ['a', 'bb', 'ccc']` |
| `reverse` | In place | `nums.reverse()` | `nums → [2, 1, 3]` |
| `copy` | Shallow copy | `nums.copy()` | `[3, 1, 2]` |
| `del s[i:j]` | Delete a slice | `del nums[:2]` | `nums → [2]` |
| `s[i:j] = t` | Replace a slice | `nums[1:] = [7]` | `nums → [3, 7]` |
| `+=` | Extend in place | `nums += (4,)` | `nums → [3, 1, 2, 4]` |

### Sorting

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `sorted` | New sorted list | `sorted('cab')` | `['a', 'b', 'c']` |
| `reverse=True` | Descending | `sorted([3, 1, 2], reverse=True)` | `[3, 2, 1]` |
| `key=str.lower` | Case-insensitive | `sorted(['b', 'A', 'c'], key=str.lower)` | `['A', 'b', 'c']` |
| `tuple key` | Multi-level sort | `sorted(['bb', 'a', 'cc'], key=lambda w: (-len(w), w))` | `['bb', 'cc', 'a']` |
| `stability` | Ties keep order | `sorted([(1, 'b'), (0, 'z'), (1, 'a')], key=lambda p: p[0])` | `[(0, 'z'), (1, 'b'), (1, 'a')]` |
| `bisect.insort` | Insert keeping order | `bisect.insort(nums, 2)` | `nums → [1, 2, 3]` |

### tuple, namedtuple, range, array

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `tuple.count` | Occurrences | `(1, 2, 1).count(1)` | `2` |
| `tuple.index` | Position | `(1, 2, 1).index(2)` | `1` |
| `one-item tuple` | Needs a comma | `type((1,)).__name__` | `'tuple'` |
| `unpacking` | Bind items | `(first, *rest) = (1, 2, 3)` | `rest → [2, 3]` |
| `namedtuple` | Fields by name | `Point(1, 2).y` | `2` |
| `_fields` | Field names | `Point._fields` | `('x', 'y')` |
| `_replace` | Copy with changes | `Point(1, 2)._replace(x=9)` | `Point(x=9, y=2)` |
| `_asdict` | To a dict | `Point(1, 2)._asdict()` | `{'x': 1, 'y': 2}` |
| `_make` | From an iterable | `Point._make([3, 4])` | `Point(x=3, y=4)` |
| `range` | Lazy arithmetic | `list(range(2, 10, 3))` | `[2, 5, 8]` |
| `range.index` | Position of value | `range(0, 20, 5).index(15)` | `3` |
| `range in` | O(1) membership | `10 ** 12 in range(10 ** 13)` | `True` |
| `range slice` | Gives a range | `range(10)[2:8:2]` | `range(2, 8, 2)` |
| `array` | Typed compact list | `array.array('i', [1, 2]).itemsize` | `4` |

## Dictionaries

Explained in [Unit 1.6](unit-1-6-collection-data-types-ii-dictionaries-sets-and-the-collections-module.md).

### Reading

Examples start from `stock = {'tea': 5, 'jam': 2}`.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `d[key]` | Value or KeyError | `stock['tea']` | `5` |
| `d[missing]` | Raises | `stock['milk']` | `KeyError` |
| `get` | Value or default | `stock.get('milk', 0)` | `0` |
| `in` | Key membership | `'tea' in stock` | `True` |
| `keys` | Live key view | `list(stock.keys())` | `['tea', 'jam']` |
| `values` | Live value view | `list(stock.values())` | `[5, 2]` |
| `items` | Live pair view | `list(stock.items())` | `[('tea', 5), ('jam', 2)]` |
| `len` | Number of keys | `len(stock)` | `2` |
| `copy` | Shallow copy | `stock.copy()` | `{'tea': 5, 'jam': 2}` |

### Writing and removing

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `d[key] = v` | Insert or replace | `stock['milk'] = 1` | `stock → {'tea': 5, 'jam': 2, 'milk': 1}` |
| `setdefault` | Get or insert | `stock.setdefault('rice', 0)` | `0; stock → {'tea': 5, 'jam': 2, 'rice': 0}` |
| `update` | Merge in place | `stock.update(jam=9)` | `stock → {'tea': 5, 'jam': 9}` |
| `\|` | Merge, new dict | `stock \| {'oil': 1}` | `{'tea': 5, 'jam': 2, 'oil': 1}` |
| `\|=` | Merge in place | `stock \|= {'tea': 0}` | `stock → {'tea': 0, 'jam': 2}` |
| `pop` | Remove, return value | `stock.pop('tea')` | `5; stock → {'jam': 2}` |
| `pop(k, default)` | No KeyError | `stock.pop('milk', None)` | `None` |
| `popitem` | Remove last pair | `stock.popitem()` | `('jam', 2); stock → {'tea': 5}` |
| `del d[key]` | Delete a key | `del stock['jam']` | `stock → {'tea': 5}` |
| `clear` | Remove all | `stock.clear()` | `stock → {}` |

### Building

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `dict(pairs)` | From pairs | `dict([('a', 1), ('b', 2)])` | `{'a': 1, 'b': 2}` |
| `dict(kw)` | From keywords | `dict(a=1, b=2)` | `{'a': 1, 'b': 2}` |
| `fromkeys` | Same value per key | `dict.fromkeys('ab', 0)` | `{'a': 0, 'b': 0}` |
| `comprehension` | Computed entries | `{w: len(w) for w in ['hi', 'tea']}` | `{'hi': 2, 'tea': 3}` |
| `zip` | Keys with values | `dict(zip('ab', [1, 2]))` | `{'a': 1, 'b': 2}` |
| `invert` | Swap keys, values | `{v: k for k, v in {'a': 1}.items()}` | `{1: 'a'}` |
| `sorted by value` | Order by value | `dict(sorted({'b': 2, 'a': 3}.items(), key=lambda kv: kv[1]))` | `{'b': 2, 'a': 3}` |
| `MappingProxyType` | Read-only view | `MappingProxyType({'a': 1})['a']` | `1` |
| `equal keys` | 1 == 1.0 == True | `len({1: 'a', 1.0: 'b', True: 'c'})` | `1` |
| `hash(list)` | Unhashable key | `hash([1])` | `TypeError` |

## Sets and frozen sets

Explained in [Unit 1.6](unit-1-6-collection-data-types-ii-dictionaries-sets-and-the-collections-module.md).

### Changing a set

Examples start from `ids = {1, 2}`. Small ints display in order; sets of strings print in an order that can change between runs.

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `add` | Add one item | `ids.add(3)` | `ids → {1, 2, 3}` |
| `update` | Add many | `ids.update([2, 3, 4])` | `ids → {1, 2, 3, 4}` |
| `remove` | Delete or KeyError | `ids.remove(9)` | `KeyError` |
| `discard` | Delete if present | `ids.discard(9)` | `ids → {1, 2}` |
| `pop` | Remove an arbitrary item | `ids.pop() in {1, 2}` | `True` |
| `clear` | Remove all | `ids.clear()` | `ids → set()` |
| `copy` | Shallow copy | `ids.copy()` | `{1, 2}` |

### Set algebra

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `union / \|` | In either | `{1, 2} \| {2, 3}` | `{1, 2, 3}` |
| `intersection / &` | In both | `{1, 2} & {2, 3}` | `{2}` |
| `difference / -` | In first only | `{1, 2} - {2, 3}` | `{1}` |
| `symmetric_difference / ^` | In exactly one | `{1, 2} ^ {2, 3}` | `{1, 3}` |
| `issubset / <=` | All in other | `{1} <= {1, 2}` | `True` |
| `issuperset / >=` | Contains other | `{1, 2} >= {2}` | `True` |
| `<` | Proper subset | `{1, 2} < {1, 2}` | `False` |
| `isdisjoint` | No common items | `{1}.isdisjoint({2})` | `True` |
| `method takes iterables` | Operators need sets | `{1}.union([2, 3])` | `{1, 2, 3}` |
| `intersection_update / &=` | In place | `nums &= {2, 3}` | `nums → {2}` |
| `difference_update / -=` | In place | `nums -= {2}` | `nums → {1}` |
| `symmetric_difference_update` | In place | `nums ^= {2, 3}` | `nums → {1, 3}` |
| `frozenset` | Hashable set | `{frozenset({1, 2}): 'pair'}[frozenset({2, 1})]` | `'pair'` |
| `dedupe, keep order` | Via dict keys | `list(dict.fromkeys('banana'))` | `['b', 'a', 'n']` |

## The collections module

Explained in [Unit 1.6](unit-1-6-collection-data-types-ii-dictionaries-sets-and-the-collections-module.md).

### Counter

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `Counter(iterable)` | Count items | `Counter('aab')` | `Counter({'a': 2, 'b': 1})` |
| `missing key` | Reads as 0 | `Counter('aab')['z']` | `0` |
| `most_common` | Top n | `Counter('mississippi').most_common(2)` | `[('i', 4), ('s', 4)]` |
| `elements` | Expand counts | `sorted(Counter(a=2, b=1).elements())` | `['a', 'a', 'b']` |
| `update` | Add counts | `c.update('aa')` | `c → Counter({'a': 3, 'b': 1})` |
| `subtract` | Subtract counts | `c.subtract('aa')` | `c → Counter({'b': 1, 'a': -1})` |
| `total` | Sum of counts | `Counter('aab').total()` | `3` |
| `+ / -` | Combine, drop <= 0 | `Counter('aab') - Counter('ab')` | `Counter({'a': 1})` |
| `& / \|` | Min / max of counts | `Counter('aab') & Counter('ab')` | `Counter({'a': 1, 'b': 1})` |

### defaultdict, OrderedDict, ChainMap

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `defaultdict(list)` | Auto-create values | `groups['a'].append(1)` | `groups → defaultdict(<class 'list'>, {'a': [1]})` |
| `defaultdict(int)` | Counting | `counts['x'] += 1` | `counts → defaultdict(<class 'int'>, {'x': 1})` |
| `default_factory` | The factory | `defaultdict(list).default_factory` | `<class 'list'>` |
| `move_to_end` | Reorder a key | `od.move_to_end('a')` | `od → OrderedDict({'b': 2, 'a': 1})` |
| `popitem(last=False)` | Pop oldest | `od.popitem(last=False)` | `('a', 1)` |
| `OrderedDict ==` | Order-sensitive | `OrderedDict(a=1, b=2) == OrderedDict(b=2, a=1)` | `False` |
| `ChainMap lookup` | First map wins | `ChainMap({'a': 1}, {'a': 2, 'b': 3})['a']` | `1` |
| `ChainMap writes` | Go to first map | `cm['b'] = 9` | `first → {'b': 9}` |
| `new_child` | Push a scope | `ChainMap({'a': 1}).new_child({'a': 0})['a']` | `0` |
| `parents` | Drop first map | `ChainMap({'a': 0}, {'a': 1}).parents['a']` | `1` |

### deque

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `append / appendleft` | Add at either end | `dq.appendleft(0)` | `dq → deque([0, 1, 2, 3])` |
| `pop / popleft` | Remove at either end | `dq.popleft()` | `1; dq → deque([2, 3])` |
| `extendleft` | Adds reversed | `dq.extendleft([8, 9])` | `dq → deque([9, 8, 1, 2, 3])` |
| `rotate` | Rotate right by n | `dq.rotate(1)` | `dq → deque([3, 1, 2])` |
| `maxlen` | Bounded, drops oldest | `dq.append(4)` | `dq → deque([2, 3, 4], maxlen=3)` |
| `insert / remove` | Like list | `dq.remove(2)` | `dq → deque([1, 3])` |
| `count / index` | Like list | `deque([1, 2, 1]).count(1)` | `2` |
| `reverse / clear` | Like list | `dq.reverse()` | `dq → deque([3, 2, 1])` |

### Classic structures with built-ins

| Structure | Use | Push | Pop |
| --- | --- | --- | --- |
| Stack | `list` | `s.append(x)` | `s.pop()` |
| Queue | `deque` | `q.append(x)` | `q.popleft()` |
| Priority queue | `heapq` on a list | `heappush(h, x)` | `heappop(h)` |
| LRU cache | `OrderedDict` | `move_to_end(k)` | `popitem(last=False)` |
| Graph | `dict[str, set]` | `g[a].add(b)` | — |

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `heapq.heappush` | Push keeping heap | `heapq.heappush(heap, 1)` | `heap → [1, 5, 2]` |
| `heapq.heappop` | Smallest first | `heapq.heappop(heap)` | `1` |
| `heapq.nsmallest` | Top n smallest | `heapq.nsmallest(2, [5, 1, 4, 2])` | `[1, 2]` |
| `heapq.nlargest` | Top n largest | `heapq.nlargest(2, [5, 1, 4, 2])` | `[5, 4]` |

## Copying

Explained in [Unit 1.7](unit-1-7-copying-shallow-copies-deep-copies-and-structured-clones.md).

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `=` | New name, same object | `alias is data` | `True` |
| `list(x) / x[:]` | Shallow copy | `data[:][0] is data[0]` | `True` |
| `dict.copy` | Shallow copy | `d.copy()['k'] is d['k']` | `True` |
| `copy.copy` | Generic shallow | `copy.copy(data)[0] is data[0]` | `True` |
| `copy.deepcopy` | Recursive copy | `copy.deepcopy(data)[0] is data[0]` | `False` |
| `memo` | Keeps shared refs | `(c := copy.deepcopy([s, s]))[0] is c[1]` | `True` |
| `cycles` | Handled by memo | `(c := copy.deepcopy(loop))[0] is c` | `True` |
| `copy.replace` | Copy with changes | `copy.replace(Point(1, 2), y=5)` | `Point(x=1, y=5)` |
| `immutable copy` | Returns the same | `copy.copy(point) is point` | `True` |

| Hook | Called by | Purpose | JS analogue |
| --- | --- | --- | --- |
| `__copy__` | `copy.copy` | Custom shallow copy | — |
| `__deepcopy__(memo)` | `copy.deepcopy` | Custom deep copy | — |
| `__replace__` | `copy.replace` | Copy with changes | spread `{...o, k}` |
| `deepcopy` | — | Structured clone | `structuredClone` |

## Operators and syntax forms

Explained in [Unit 1.8](unit-1-8-operators-expressions-and-control-flow.md).

### Operators

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `==` | Equal values | `[1] == [1]` | `True` |
| `is` | Same object | `[1] is [1]` | `False` |
| `chained` | a < b < c | `1 < 2 < 3` | `True` |
| `and` | First falsy or last | `0 and 1 / 0` | `0` |
| `or` | First truthy or last | `'' or 'default'` | `'default'` |
| `not` | Boolean negation | `not []` | `True` |
| `ternary` | x if cond else y | `'even' if 4 % 2 == 0 else 'odd'` | `'even'` |
| `:=` | Assign in an expression | `(n := 5) * 2` | `10` |
| `in` | Membership | `'a' in {'a': 1}` | `True` |
| `~ & \| ^` | Bitwise | `(~5, 6 & 3, 6 \| 3, 6 ^ 3)` | `(-6, 2, 7, 5)` |
| `<< >>` | Shifts | `(1 << 4, 256 >> 2)` | `(16, 64)` |
| `@` | Matrix multiply | `a @ b` | `a.__matmul__(b)` |
| `precedence` | ** binds tighter | `-2 ** 2` | `-4` |
| `precedence` | not is low | `not 1 == 2` | `True` |

### Syntax forms

| Form | Example | JS equivalent |
| --- | --- | --- |
| if / elif / else | `if x: ... elif y: ... else: ...` | `if / else if` |
| Conditional expression | `a if cond else b` | `cond ? a : b` |
| match literal | `case 200 \| 201:` | `case 200: case 201:` |
| match sequence | `case [first, *rest]:` | destructuring |
| match mapping | `case {"type": "click"}:` | — |
| match class | `case Point(x=0):` | — |
| match guard | `case x if x > 0:` | — |
| match capture | `case [x, y] as pair:` | — |
| wildcard | `case _:` | `default:` |
| for loop | `for item in items:` | `for (const item of items)` |
| while loop | `while cond:` | `while (cond)` |
| loop else | `for ...: ... else: ...` | — |
| break / continue | `break`, `continue` | same |
| pass | `pass` | `{}` |
| Multiple assign | `a = b = 0` | `a = b = 0` |
| Swap | `a, b = b, a` | `[a, b] = [b, a]` |
| Augmented | `total += 1` | same |
| Walrus | `while (line := f.readline()):` | assignment in condition |
| Star unpack | `first, *rest = items` | `[first, ...rest]` |
| Spread into call | `f(*args, **kwargs)` | `f(...args)` |
| Spread literal | `[*a, *b]`, `{**d1, **d2}` | `[...a]`, `{...o}` |

> **Note:** sequence patterns match lists and tuples, never `str`; a mapping pattern matches if the listed keys are present (extra keys are ignored).

## Built-in functions

Explained in [Unit 1.9](unit-1-9-iteration-comprehensions-and-built-in-functions.md).

### Iteration and aggregation

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `len` | Size | `len('tea')` | `3` |
| `sum` | Total (with start) | `sum([1, 2], 10)` | `13` |
| `min / max` | With key, default | `max(['aa', 'b'], key=len)` | `'aa'` |
| `max(default=)` | Empty-safe | `max([], default=0)` | `0` |
| `any` | Any truthy? | `any([0, '', 3])` | `True` |
| `all` | All truthy? | `all([])` | `True` |
| `sorted` | New sorted list | `sorted({3, 1, 2})` | `[1, 2, 3]` |
| `reversed` | Reverse iterator | `list(reversed([1, 2, 3]))` | `[3, 2, 1]` |
| `enumerate` | Index, item pairs | `list(enumerate('ab', start=1))` | `[(1, 'a'), (2, 'b')]` |
| `zip` | Pair up iterables | `list(zip('ab', [1, 2]))` | `[('a', 1), ('b', 2)]` |
| `zip(strict=True)` | Lengths must match | `list(zip('ab', [1], strict=True))` | `ValueError` |
| `map` | Apply lazily | `list(map(str.upper, 'ab'))` | `['A', 'B']` |
| `filter` | Keep truthy results | `list(filter(None, [0, 1, '', 'a']))` | `[1, 'a']` |
| `iter` | Get an iterator | `next(iter([7, 8]))` | `7` |
| `iter(callable, sentinel)` | Call until sentinel | `list(iter([3, 2, 0, 1].pop, 0))` | `[1]` |
| `next` | Next item or default | `next(iter([]), 'done')` | `'done'` |
| `range` | Arithmetic sequence | `list(range(3))` | `[0, 1, 2]` |
| `slice` | A slice object | `'abcdef'[slice(1, 4)]` | `'bcd'` |

### Numbers and characters

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `abs` | Absolute value | `abs(-3)` | `3` |
| `round` | Half to even | `round(0.5)` | `0` |
| `divmod` | Quotient, remainder | `divmod(7, 2)` | `(3, 1)` |
| `pow` | Power, optional mod | `pow(2, 10)` | `1024` |
| `bin / oct / hex` | Base strings | `(bin(5), oct(8), hex(255))` | `('0b101', '0o10', '0xff')` |
| `chr` | Code point to char | `chr(8377)` | `'₹'` |
| `ord` | Char to code point | `ord('A')` | `65` |
| `ascii` | Escape non-ASCII | `ascii('café')` | `"'caf\\xe9'"` |
| `repr` | Developer string | `repr('hi')` | `"'hi'"` |
| `format` | Apply a format spec | `format(0.5, '.0%')` | `'50%'` |
| `hash` | Hash value of key | `hash(1) == hash(1.0)` | `True` |

### Types and conversion

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `int / float / complex` | Numbers | `(int('7'), float('7'), complex('1+2j'))` | `(7, 7.0, (1+2j))` |
| `str / bytes / bytearray` | Text and binary | `bytes('hi', 'ascii')` | `b'hi'` |
| `bool` | Truth value | `bool([])` | `False` |
| `list / tuple / set` | Containers | `tuple('ab')` | `('a', 'b')` |
| `dict / frozenset` | Mappings, frozen set | `frozenset([2, 1, 2])` | `frozenset({1, 2})` |
| `memoryview` | Buffer view | `memoryview(b'ab').nbytes` | `2` |
| `object` | Base of all types | `isinstance(3, object)` | `True` |
| `type` | The class of x | `type(3.0).__name__` | `'float'` |
| `isinstance` | Type check | `isinstance(True, (int, str))` | `True` |
| `issubclass` | Class check | `issubclass(bool, int)` | `True` |
| `callable` | Can be called? | `callable(len)` | `True` |

### Objects and attributes

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `id` | Identity (varies) | `id(None) == id(None)` | `True` |
| `getattr` | Read, with default | `getattr('hi', 'nope', 'n/a')` | `'n/a'` |
| `setattr` | Write an attribute | `setattr(ns, 'x', 1)` | `ns → namespace(x=1)` |
| `hasattr` | Attribute exists? | `hasattr('hi', 'upper')` | `True` |
| `delattr` | Delete an attribute | `delattr(ns, 'x')` | `ns → namespace()` |
| `dir` | List attribute names | `'upper' in dir(str)` | `True` |
| `vars` | An object's __dict__ | `vars(types.SimpleNamespace(a=1))` | `{'a': 1}` |
| `globals / locals` | Namespace dicts | `type(globals()).__name__` | `'dict'` |
| `property` | Managed attribute | `@property` | `see Phase 2` |
| `classmethod / staticmethod` | Method kinds | `@classmethod` | `see Phase 2` |
| `super` | Parent class lookup | `super().__init__()` | `see Phase 2` |

### Code and I/O

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `eval` | Evaluate an expression | `eval('2 * 21')` | `42` |
| `exec` | Run statements | `exec('x = 5', scope) or scope['x']` | `5` |
| `compile` | Source to code object | `type(compile('1', '<s>', 'eval')).__name__` | `'code'` |
| `print` | Write to stdout | `print('a', 'b', sep='-')` | `prints a-b` |
| `input` | Read a line | `input('Name? ')` | `str typed by user` |
| `open` | Open a file | `open('f.txt', encoding='utf-8')` | `file object` |
| `help` | Interactive help | `help(len)` | `prints docs` |
| `breakpoint` | Start the debugger | `breakpoint()` | `enters pdb` |
| `__import__` | Import by name | `__import__('math').pi > 3` | `True` |
| `aiter / anext` | Async iteration | `anext(agen)` | `awaitable (Phase 5)` |

### Comprehensions

| Kind | Example | Result |
| --- | --- | --- |
| List | `[n * n for n in range(4)]` | `[0, 1, 4, 9]` |
| Filtered | `[n for n in range(6) if n % 2]` | `[1, 3, 5]` |
| If-else value | `['e' if n % 2 == 0 else 'o' for n in range(3)]` | `['e', 'o', 'e']` |
| Nested | `[(r, c) for r in 'ab' for c in '12']` | 4 pairs, `r` outer |
| Dict | `{w: len(w) for w in ['hi', 'tea']}` | `{'hi': 2, 'tea': 3}` |
| Set | `{n % 3 for n in range(10)}` | `{0, 1, 2}` |
| Generator | `sum(n * n for n in range(4))` | `14` |

## Functions and parameters

Explained in [Unit 1.10](unit-1-10-functions-definition-and-arguments.md).

| Kind | Syntax | Call with |
| --- | --- | --- |
| Positional-or-keyword | `def f(a):` | `f(1)` or `f(a=1)` |
| Default | `def f(a=0):` | `f()` |
| Positional-only | `def f(a, /):` | `f(1)` only |
| Keyword-only | `def f(*, a):` | `f(a=1)` only |
| Var-positional | `def f(*args):` | `f(1, 2)` → tuple |
| Var-keyword | `def f(**kwargs):` | `f(a=1)` → dict |
| Full order | `def f(a, /, b, *args, c, **kw):` | — |
| Unpack a list | `f(*items)` | spread positional |
| Unpack a dict | `f(**options)` | spread keywords |
| Lambda | `lambda x: x * 2` | one expression |

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `mutable default` | Shared between calls | `f(1) + f(2)` | `[1, 2, 1, 2]` |
| `None default` | The fix | `f(1) + f(2)` | `[1, 2]` |
| `no return` | Returns None | `f() is None` | `True` |
| `multiple returns` | Returns a tuple | `f()` | `(1, 2)` |
| `__defaults__` | Stored defaults | `f.__defaults__` | `(2, 3)` |
| `__annotations__` | Type hints | `f.__annotations__` | `{'a': <class 'int'>, 'return': <class 'str'>}` |
| `__doc__` | Docstring | `f.__doc__` | `'Say hi.'` |
| `functions are objects` | Store in a dict | `{'up': str.upper}['up']('hi')` | `'HI'` |

## Scope rules

Explained in [Unit 1.11](unit-1-11-scope-namespaces-and-closures.md).

| Rule | Meaning | JS difference |
| --- | --- | --- |
| LEGB | Local → Enclosing → Global → Built-in | Similar chain |
| No block scope | `if`/`for` don't create a scope | Unlike `let` |
| Loop variable leaks | `for i in ...` keeps `i` after | Unlike `let i` |
| Comprehension scope | Own scope; name does not leak | — |
| Assign = local | Any assignment makes a name local | No hoisting of `var` |
| Compile-time decision | Read before assign → `UnboundLocalError` | TDZ-like |
| `global name` | Assign to a module name | — |
| `nonlocal name` | Assign to an enclosing name | Closures assign freely |
| Closures | Inner functions keep enclosing cells | Same idea |
| Late binding | Closures see the variable, not value | Same as `var` loops |

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `UnboundLocalError` | Assign makes it local | `f()` | `UnboundLocalError` |
| `nonlocal` | Rebind enclosing | `(c := make())() + c()` | `3` |
| `__closure__` | Captured cells | `len(make().__closure__)` | `1` |
| `co_freevars` | Names captured | `make().__code__.co_freevars` | `('n',)` |
| `late binding` | Last value wins | `[f() for f in [lambda: i for i in range(3)]]` | `[2, 2, 2]` |
| `default fix` | Bind value now | `[f() for f in [lambda i=i: i for i in range(3)]]` | `[0, 1, 2]` |

## Decorators, functools, operator

Explained in [Unit 1.12](unit-1-12-decorators-functools-and-the-call-stack.md).

| Form | Means | Note |
| --- | --- | --- |
| `@decorator` | `f = decorator(f)` | Runs at `def` time |
| `@factory(arg)` | `f = factory(arg)(f)` | Factory returns decorator |
| `@a` over `@b` | `f = a(b(f))` | Bottom-up |
| `@functools.wraps(f)` | Copy name, doc, `__wrapped__` | Always use it |
| Class decorator | `__call__` on an instance | Holds state |
| Decorating a class | `C = deco(C)` | e.g. register |

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `lru_cache` | Memoise, bounded | `fib(30)` | `832040` |
| `cache` | Unbounded lru_cache | `functools.cache(abs)(-3)` | `3` |
| `cache_info` | Hit statistics | `sq.cache_info().misses` | `1` |
| `partial` | Pre-fill arguments | `functools.partial(int, base=2)('101')` | `5` |
| `reduce` | Fold to one value | `functools.reduce(operator.mul, [1, 2, 3, 4])` | `24` |
| `wraps` | Keep metadata | `w.__name__` | `'w'` |
| `total_ordering` | Fill in comparisons | `@functools.total_ordering` | `see Phase 2` |
| `singledispatch` | Dispatch on type | `show(1), show('a')` | `('int', 'any')` |
| `cached_property` | Compute once | `@functools.cached_property` | `see Phase 2` |
| `cmp_to_key` | Old-style compare | `sorted([3, 1], key=functools.cmp_to_key(lambda a, b: a - b))` | `[1, 3]` |

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `itemgetter` | Fetch by key/index | `operator.itemgetter(1)('abc')` | `'b'` |
| `itemgetter(many)` | Several at once | `operator.itemgetter(0, 2)('abc')` | `('a', 'c')` |
| `attrgetter` | Fetch an attribute | `operator.attrgetter('real')(3 + 4j)` | `3.0` |
| `methodcaller` | Call a method | `operator.methodcaller('upper')('hi')` | `'HI'` |
| `add / mul` | Operators as functions | `operator.add(2, 3)` | `5` |

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `sys.getrecursionlimit` | Max depth | `sys.getrecursionlimit()` | `1000` |
| `RecursionError` | Too deep | `f(0)` | `RecursionError` |
| `sys._getframe` | Current frame | `sys._getframe().f_code.co_name` | `'<module>'` |
| `inspect.signature` | Parameter list | `str(__import__('inspect').signature(lambda a, *, b=1: 0))` | `'(a, *, b=1)'` |
| `__qualname__` | Dotted name | `outer().__qualname__` | `'outer.<locals>.inner'` |

## Iterators, generators, itertools

Explained in [Unit 1.13](unit-1-13-iterators-generators-and-itertools.md).

| Concept | Python | JS equivalent |
| --- | --- | --- |
| Iterable | has `__iter__` | has `[Symbol.iterator]` |
| Iterator | has `__next__`, raises `StopIteration` | `next()` → `{done}` |
| Generator function | `def f(): yield x` | `function* f()` |
| Generator expression | `(x for x in xs)` | — |
| Delegate | `yield from inner` | `yield* inner` |
| Send a value | `gen.send(value)` | `gen.next(value)` |
| Stop early | `gen.close()` | `gen.return()` |
| Throw in | `gen.throw(exc)` | `gen.throw(err)` |
| Return value | `StopIteration.value` | `{value, done: true}` |

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `single use` | Exhausts once | `(sum(g), sum(g))` | `(6, 0)` |
| `send` | Two-way | `(next(acc), acc.send(5), acc.send(2))` | `(0, 5, 7)` |
| `yield from result` | Gets return value | `list(outer())` | `[1, 2]` |
| `getgeneratorstate` | Lifecycle | `__import__('inspect').getgeneratorstate(g)` | `'GEN_CREATED'` |

### itertools — infinite and terminating

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `count` | Endless counter | `list(itertools.islice(itertools.count(10, 5), 3))` | `[10, 15, 20]` |
| `cycle` | Repeat forever | `list(itertools.islice(itertools.cycle('ab'), 5))` | `['a', 'b', 'a', 'b', 'a']` |
| `repeat` | Same value n times | `list(itertools.repeat('x', 3))` | `['x', 'x', 'x']` |
| `islice` | Slice an iterator | `list(itertools.islice('abcdef', 1, 5, 2))` | `['b', 'd']` |
| `chain` | Concatenate | `list(itertools.chain('ab', 'cd'))` | `['a', 'b', 'c', 'd']` |
| `chain.from_iterable` | Flatten one level | `list(itertools.chain.from_iterable([[1], [2, 3]]))` | `[1, 2, 3]` |
| `accumulate` | Running totals | `list(itertools.accumulate([1, 2, 3]))` | `[1, 3, 6]` |
| `batched` | Fixed-size chunks | `list(itertools.batched('abcde', 2))` | `[('a', 'b'), ('c', 'd'), ('e',)]` |
| `pairwise` | Overlapping pairs | `list(itertools.pairwise('abc'))` | `[('a', 'b'), ('b', 'c')]` |
| `compress` | Select by flags | `list(itertools.compress('abc', [1, 0, 1]))` | `['a', 'c']` |
| `takewhile` | Take while true | `list(itertools.takewhile(lambda n: n < 3, [1, 2, 5, 1]))` | `[1, 2]` |
| `dropwhile` | Skip while true | `list(itertools.dropwhile(lambda n: n < 3, [1, 2, 5, 1]))` | `[5, 1]` |
| `filterfalse` | Keep falsy results | `list(itertools.filterfalse(None, [0, 1, 0, 2]))` | `[0, 0]` |
| `starmap` | Map over arg tuples | `list(itertools.starmap(pow, [(2, 3), (3, 2)]))` | `[8, 9]` |
| `zip_longest` | Zip, pad shortest | `list(itertools.zip_longest('ab', 'x', fillvalue='-'))` | `[('a', 'x'), ('b', '-')]` |
| `groupby` | Group consecutive | `[(k, len(list(g))) for k, g in itertools.groupby('aabaa')]` | `[('a', 2), ('b', 1), ('a', 2)]` |
| `tee` | Split one iterator | `[list(t) for t in itertools.tee('ab', 2)]` | `[['a', 'b'], ['a', 'b']]` |

### itertools — combinatorics

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `product` | Cartesian product | `len(list(itertools.product('ab', repeat=2)))` | `4` |
| `permutations` | Ordered picks | `list(itertools.permutations('abc', 2))[:3]` | `[('a', 'b'), ('a', 'c'), ('b', 'a')]` |
| `combinations` | Unordered picks | `list(itertools.combinations('abc', 2))` | `[('a', 'b'), ('a', 'c'), ('b', 'c')]` |
| `combinations_with_replacement` | With repeats | `list(itertools.combinations_with_replacement('ab', 2))` | `[('a', 'a'), ('a', 'b'), ('b', 'b')]` |

## Exceptions and context managers

Explained in [Unit 1.14](unit-1-14-exceptions-and-context-managers.md).

### Statements

| Form | Runs when | JS equivalent |
| --- | --- | --- |
| `try:` | Always, first | `try {` |
| `except E as err:` | `E` (or subclass) raised | `catch (err)` + check |
| `except (A, B):` | Either type | — |
| `else:` | No exception, no early exit | — |
| `finally:` | Always, on the way out | `finally` |
| `raise E(msg)` | Raise | `throw new E(msg)` |
| `raise` | Re-raise current | `throw err` |
| `raise B from A` | Explicit cause | `new B(msg, {cause})` |
| `raise B from None` | Hide the context | — |
| `except* E:` | Members of a group | — |
| `with cm as x:` | Enter / exit | `using` (TC39) |
| `assert cond, msg` | Debug check (off with -O) | `console.assert` |

### Hierarchy and exception objects

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `BaseException` | Root of all | `issubclass(KeyboardInterrupt, Exception)` | `False` |
| `Exception` | Catch this, not Base | `issubclass(ValueError, Exception)` | `True` |
| `LookupError` | Key and index errors | `issubclass(KeyError, LookupError)` | `True` |
| `OSError family` | File, network errors | `issubclass(FileNotFoundError, OSError)` | `True` |
| `ArithmeticError` | Math errors | `issubclass(ZeroDivisionError, ArithmeticError)` | `True` |
| `args` | Constructor arguments | `ValueError('bad', 42).args` | `('bad', 42)` |
| `str(err)` | The message | `str(KeyError('sku'))` | `"'sku'"` |
| `add_note` | Attach context | `e.__notes__` | `['row 3']` |
| `__cause__` | Set by from | `e.__cause__` | `ZeroDivisionError('division by zero')` |
| `__traceback__` | Where it was raised | `e.__traceback__ is not None` | `True` |
| `ExceptionGroup` | Many errors as one | `len(ExceptionGroup('m', [ValueError(), KeyError()]).exceptions)` | `2` |
| `split` | Partition a group | `[len(p.exceptions) for p in eg.split(ValueError)]` | `[1, 1]` |

### contextlib

| Method | What it does | Example | Result |
| --- | --- | --- | --- |
| `contextmanager` | Generator-based CM | `list(use())` | `['value', 'in', 'out']` |
| `suppress` | Ignore an error | `d.get('k')` | `None` |
| `closing` | Call close() on exit | `t.closed` | `True` |
| `ExitStack` | Dynamic number of CMs | `es.enter_context(contextlib.nullcontext(7))` | `7` |
| `redirect_stdout` | Capture print | `buf.getvalue()` | `'hi\n'` |
| `nullcontext` | Do-nothing CM | `contextlib.nullcontext(5).__enter__()` | `5` |
| `chdir` | Temporary cwd | `with contextlib.chdir(path):` | `restores the cwd` |

### Protocol and warnings

| Piece | Role | Note |
| --- | --- | --- |
| `__enter__(self)` | Set up; value bound by `as` | Often returns `self` |
| `__exit__(self, t, v, tb)` | Tear down | Truthy return swallows the error |
| EAFP | `try: d[k] except KeyError:` | Pythonic default |
| LBYL | `if k in d: d[k]` | Race-prone for files |
| `logging.exception` | Log with traceback | Inside `except` only |
| `warnings.warn(msg, Cat)` | Non-fatal notice | Filterable |
| `warnings.catch_warnings` | Scope a filter | Use in tests |

## Further reading

- [Built-in functions](https://docs.python.org/3/library/functions.html)
- [Built-in types](https://docs.python.org/3/library/stdtypes.html)
- [collections](https://docs.python.org/3/library/collections.html)
- [itertools](https://docs.python.org/3/library/itertools.html)
- [functools](https://docs.python.org/3/library/functools.html)
- [contextlib](https://docs.python.org/3/library/contextlib.html)
- [Built-in exceptions](https://docs.python.org/3/library/exceptions.html)
- [Format specification](https://docs.python.org/3/library/string.html#formatspec)

[← Previous](project-log-analyzer.md) · [Index](README.md)
