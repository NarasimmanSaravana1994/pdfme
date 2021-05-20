from copy import deepcopy
import re
from .color import PDFColor
from .utils import parse_style_str, default, process_style
from .standard_fonts import STANDARD_FONTS

PARAGRAPH_DEFAULTS = {'height': 200, 'width': 200, 'text_align': 'l',
                      'line_height': 1.1, 'indent': 0}

TEXT_DEFAULTS = {'f': 'Helvetica', 'c': 0.1, 's': 11, 'r': 0, 'bg': None}


class PDFState:
    def __init__(self, style, fonts=None):

        self.fonts = STANDARD_FONTS if fonts is None else fonts

        self.font_family = style['f']

        f_mode = ''
        if style.get('b', False):
            f_mode += 'b'
        if style.get('i', False):
            f_mode += 'i'
        if f_mode == '':
            f_mode = 'n'
        self.font_mode = 'n' if not f_mode in fonts[style['f']] else f_mode

        self.size = style['s']
        self.color = PDFColor(style['c'])
        self.rise = style.get('r', 0) * self.size

    def compare(self, other):
        ret_value = ''
        if (
            other is None or self.font_family != other.font_family or
            self.font_mode != other.font_mode or self.size != other.size
        ):
            ret_value += ' /{} {} Tf'.format(
                self.fonts[self.font_family][self.font_mode]['ref'],
                round(self.size, 3)
            )
        if other is None or self.color != other.color:
            ret_value += ' ' + str(self.color)
        if other is None or self.rise != other.rise:
            ret_value += ' {} Ts'.format(round(self.rise, 3))

        return ret_value


class PDFTextLinePart:
    def __init__(self, style, fonts=None, ids=None):

        self.fonts = STANDARD_FONTS if fonts is None else fonts

        self.style = style
        self.state = PDFState(style, fonts)
        self.underline = style.get('u', False)
        self.background = PDFColor(style.get('bg'))
        self.ids = [] if id is None else ids
        self.width = 0
        self.words = []

        self.space_width = self.get_char_width(' ')
        self.spaces_width = 0

    def pop_word(self, index=None):
        if len(self.words) > 0:
            word = str(
                self.words.pop() if index is None else self.words.pop(index)
            )
            if word == ' ':
                self.spaces_width -= self.space_width
            else:
                self.width -= self.get_word_width(word)
            return word

    def add_word(self, word):
        self.words.append(word)
        word_ = str(word)
        if word_ == ' ':
            self.spaces_width += self.space_width
        else:
            self.width += self.get_word_width(word_)

    def current_width(self, factor=1):
        return self.width + self.spaces_width*factor

    def tentative_width(self, word, factor=1):
        word_width = self.space_width * factor if word == ' ' else \
            self.get_word_width(word)
        return self.current_width(factor) + word_width

    def get_char_width(self, char):
        ws = self.fonts[self.state.font_family][self.state.font_mode]['widths']
        return self.state.size * ws[char] / 1000

    def get_word_width(self, word):
        return sum(self.get_char_width(char) for char in word)

class PDFTextLine:
    def __init__(
        self, fonts=None, max_width=0, text_align=None, line_height=None,
        top_margin=0
    ):
        self.fonts = STANDARD_FONTS if fonts is None else fonts
        self.max_width = max_width
        self.line_parts = []

        self.justify_min_factor = 0.7

        self.text_align = default(text_align, PARAGRAPH_DEFAULTS['text_align'])
        self.line_height = default(
            line_height, PARAGRAPH_DEFAULTS['line_height']
        )

        self.top_margin = top_margin
        self.next_line = None
        self.is_last_word_space = True
        self.firstWordAdded = False
        self.started = False

    @property
    def height(self):
        top = 0
        height_ = 0
        for part in self.line_parts:
            if part.state.rise > 0 and part.state.rise > top:
                top = part.state.rise
            if part.state.size > height_:
                height_ = part.state.size

        return height_ + self.top_margin + top

    @property
    def min_width(self):
        ws = self.get_widths()
        return ws[0] + ws[1] * self.factor

    @property
    def factor(self):
        return 1 if self.text_align != 'j' else self.justify_min_factor

    @property
    def bottom(self):
        bottom = 0
        for part in self.line_parts:
            if part.state.rise < 0 and -part.state.rise > bottom:
                bottom = -part.state.rise
        return bottom

    def get_widths(self):
        words_width = 0
        spaces_width = 0
        for part in self.line_parts:
            words_width += part.width
            spaces_width += part.spaces_width
        return words_width, spaces_width

    def add_line_part(self, style=None, ids=None):
        if self.next_line is None:
            self.next_line = PDFTextLine(
                self.fonts, self.max_width, self.text_align, self.line_height
            )

        line_part = PDFTextLinePart(style, self.fonts, ids)
        self.next_line.line_parts.append(line_part)
        return line_part

    def add_accumulated(self):
        self.line_parts.extend(self.next_line.line_parts)
        last_part = self.line_parts[-1]
        last_part.add_word(' ')
        self.next_line.line_parts = [
            PDFTextLinePart(last_part.style, self.fonts, last_part.ids)
        ]

    def add_word(self, word, new_width):
        if self.next_line is None:
            raise Exception(
                'You have to add a line_part, using method "add_line_part" to '
                'this line, before adding a word'
            )

        if not self.started:
            if word.isspace():
                if self.firstWordAdded:
                    self.started = True
                    self.add_accumulated()
                    return {'status': 'added'}
                else:
                    return {'status': 'ignored'}
            else:
                self.firstWordAdded = True
                self.next_line.line_parts[-1].add_word(word)
                return {'status': 'added'}
        else:
            if word.isspace():
                if self.is_last_word_space:
                    return {'status': 'ignored'}
                else:
                    self.add_accumulated()
                    return {'status': 'added'}
            else:
                self.is_last_word_space = False
                self.next_line.line_parts[-1].add_word(word)
                if (self.min_width + self.next_line.min_width < self.max_width):
                    return {'status': 'preadded'}
                else:
                    if (
                        len(self.line_parts[-1].words) and
                        self.line_parts[-1].words[-1] == ' '
                    ):
                        self.line_parts[-1].pop_word(-1)
                    self.next_line.firstWordAdded = True
                    self.next_line.top_margin = self.bottom
                    self.next_line.next_line = PDFTextLine(
                        self.fonts, new_width, self.text_align, self.line_height
                    )
                    line_parts = self.next_line.line_parts
                    self.next_line.next_line.line_parts = line_parts
                    self.next_line.line_parts = []
                    return {
                        'status': 'finished', 'new_line': self.next_line  
                    }

class PDFTextBase:
    def __init__(
        self, content, width, height, x=0, y=0, fonts=None, text_align=None,
        line_height=None, indent=0, list_text=None, list_indent=0,
        list_style=None
    ):
        self.fonts = STANDARD_FONTS if fonts is None else fonts
        self.used_fonts = set([])

        self.width = default(width, PARAGRAPH_DEFAULTS['width'])
        self.height = max(0, default(height, PARAGRAPH_DEFAULTS['height']))
        self.x = x
        self.y = y
        self.indent = indent
        self.text_align = default(text_align, PARAGRAPH_DEFAULTS['text_align'])
        self.line_height = default(line_height, PARAGRAPH_DEFAULTS['line_height'])
        self.list_text = list_text
        self.list_indent = list_indent
        self.list_style = list_style

        if isinstance(content, str):
            content = [{'style': TEXT_DEFAULTS.copy(), 'text': content}]
        if not isinstance(content, (list, tuple)):
            raise TypeError(
                'content must be of type str, list or tuple: {}'.format(content)
            )

        self.last_part_index = 0
        self.last_word_index = 0

        self.content = content
        self.finished = False
        self.is_first_line = True
        self.correct_indent = True
        self.list_setup_done = False

    @property
    def stream(self):
        stream = ''
        x, y = round(self.x, 3), round(self.y, 3)
        if self.graphics != '':
            stream += ' q 1 0 0 1 {} {} cm{} Q'.format(x, y, self.graphics)

        stream += ' BT 1 0 0 1 {} {} Tm{} ET'.format(x, y, self.text)
        return stream

    def move(self, x, y):
        self.x = x
        self.y = y

    def setup(self, x=None, y=None, width=None, height=None):
        if x is not None:
            self.x = x
        if y is not None:
            self.y = y
        if width is not None:
            self.width = width
        if height is not None:
            self.height = height

    def init(self):
        self.started = False
        self.lines = []
        self.text = ''
        self.graphics = ''
        self.ids = {}

        self.current_height = 0
        self.current_line_used_fonts = set()
        self.lines = []

        line_width = self.width - self.list_indent
        if self.is_first_line:
            line_width -= self.indent

        self.current_line = PDFTextLine(
            self.fonts, line_width, self.text_align, self.line_height
        )

        self.last_indent = 0
        self.last_state = self.last_factor = self.last_fill = None
        self.last_color = self.last_stroke_width = None

        self.y_ = 0

    def run(self):
        self.init()
        for part_index in range(self.last_part_index, len(self.content)):
            part = self.content[part_index]
            if not isinstance(part, dict):
                raise TypeError(
                    'elements in content must be of type dict: {}'
                    .format(part)
                )
            if 'type' in part:
                if part['type'] == 'br':
                    continue_ = self.add_current_line()
                    if continue_:
                        self.last_part_index = part_index + 1
                        self.last_word_index = 0
                    else:
                        return False
            else:
                continue_ = self.add_part(part, part_index)
                if not continue_:
                    return False


        continue_ = self.add_current_line(True)
        if continue_:
            self.finished = True
        return self.finished

    def add_part(self, part, part_index):
        words = part.get('text')
        if not isinstance(words, (str, list, tuple)):
            return 'continue'

        style = TEXT_DEFAULTS.copy()
        style.update(part.get('style', {}))
        new_line_part = self.current_line.add_line_part(
            style=style, ids=part.get('ids')
        )

        if not self.list_setup_done and self.list_text:
            self.list_setup_done = True
            self.setup_list()

        self.current_line_used_fonts.add((
            new_line_part.state.font_family,
            new_line_part.state.font_mode
        ))

        if isinstance(words, str):
            part['text'] = words = [
                ' ' if w.isspace() else w
                for w in re.split('( +)', words)
                if w != ''
            ]
        for word_index in range(self.last_word_index, len(words)):
            word = words[word_index]
            ans = self.current_line.add_word(word, self.width-self.list_indent)
            if ans['status'] == 'added':
                self.last_part_index = part_index + 1
                self.last_word_index = 0
            elif ans['status'] == 'finished':
                continue_ = self.add_current_line(
                    part_index == len(self.content) - 1 and
                    word_index == len(words) - 1
                )
                self.current_line = ans['new_line']
                if not continue_:
                    return False

        return True

    def add_current_line(self, is_last=False):
        line_height = self.current_line.height * self.line_height
        if line_height + self.current_height > self.height:
            return False
        else:
            self.current_height += line_height
            self.lines.append(self.current_line)
            self.used_fonts.update(self.current_line_used_fonts)
            self.current_line_used_fonts = set()

            self.add_line_to_stream(self.current_line)

            return True

    def setup_list(self):
        style = self.current_line.next_line.line_parts[0].style.copy()

        if self.list_style is None:
            self.list_style = {}
        elif isinstance(self.list_style, str):
            self.list_style = parse_style_str(self.list_style, self.fonts)

        if not isinstance(self.list_style, dict):
            raise TypeError(
                'list_style must be a str or a dict. Value: {}'
                .format(self.list_style)
            )

        style.update(self.list_style)
        line_part = PDFTextLinePart(style, self.fonts)

        self.current_line_used_fonts.add(
            (line_part.state.font_family, line_part.state.font_mode)
        )

        if self.list_indent is None:
            self.list_indent = line_part.get_word_width(self.list_text)
        elif not isinstance(self.list_indent, (float, int)):
            raise TypeError(
                'list_indent must be int or float. Value: {}'
                .format(self.list_style)
            )

        self.list_state = line_part.state

    def add_line_to_stream(self, line, is_last=False):
        words_width, spaces_width = line.get_widths()
        x = self.list_indent if self.list_text else 0
        line_height = line.height
        full_line_height = line_height
        ignore_factor = self.text_align != 'j' or is_last or spaces_width == 0
        factor_width = self.width - self.list_indent - words_width
        if not self.started:
            self.started = True
            if self.is_first_line:
                factor_width -= self.indent
                self.is_first_line = False
                if self.list_text:
                    if self.list_state.size > full_line_height:
                        full_line_height = self.list_state.size

                    self.text += ' 0 -{} Td{} ({})Tj {} 0 Td'.format(
                        round(full_line_height, 3),
                        self.list_state.compare(self.last_state),
                        self.list_text, self.list_indent + self.indent
                    )
                else:
                    self.text += ' {} -{} Td'.format(
                        round(self.indent, 3), round(full_line_height, 3)
                    )
            else:
                first_indent = self.list_indent if self.list_text else 0
                self.text += ' {} -{} Td'.format(
                    round(first_indent, 3), round(full_line_height, 3)
                )
        else:
            adjusted_indent = 0
            if self.text_align in ['r', 'c']:
                indent = self.width - words_width - spaces_width
                if self.text_align == 'c':
                    indent /= 2
                x += indent
                adjusted_indent = indent - self.last_indent
                self.last_indent = indent

            if self.correct_indent:
                self.correct_indent = False
                adjusted_indent -= self.indent

            full_line_height *= self.line_height

            self.text += ' {} -{} Td'.format(round(adjusted_indent, 3),
                                        round(full_line_height, 3))

        self.y_ -= full_line_height

        factor = 1 if ignore_factor else factor_width / spaces_width

        for part in line.line_parts:
            self.text += self.output_text(part, factor)
            part_width = part.current_width(factor)
            part_size = round(part.state.size, 3)

            if part.ids is not None:
                for id_ in part.ids:
                    self.ids.setdefault(id_, []).append([
                        round(x, 3),
                        round(self.y_ + part.state.rise - part_size*0.25, 3),
                        round(x + part_width, 3), round(part_size, 3)
                    ])

            part_graphics = self.output_graphics(part, x, self.y_, part_width)

            self.graphics += part_graphics
            x += part_width

    def output_text(self, part, factor=1):
        stream = part.state.compare(self.last_state)
        self.last_state = part.state

        tw = round(part.space_width * (factor - 1), 3)
        if self.last_factor != tw:
            if tw == 0:
                tw = 0
            stream += ' {} Tw'.format(tw)
            self.last_factor = tw

        text = ''.join(str(word) for word in part.words)
        if text != '':
            stream += ' ({})Tj'.format(text)

        return stream

    def output_graphics(self, part, x, y, part_width):
        graphics = ''
        if part.background is not None and not part.background.color is None:
            if part.background != self.last_fill:
                self.last_fill = part.background
                graphics += ' ' + str(self.last_fill)

            graphics += ' {} {} {} {} re F'.format(
                round(x, 3),
                round(y + part.state.rise - part.state.size*0.25, 3),
                round(part_width, 3), round(part.state.size, 3)
            )

        if part.underline:
            color = PDFColor(part.state.color, True)
            stroke_width = part.state.size * 0.1
            y_u = round(y + part.state.rise - stroke_width, 3)

            if color != self.last_color:
                self.last_color = color
                graphics += ' ' + str(self.last_color)

            if stroke_width != self.last_stroke_width:
                self.last_stroke_width = stroke_width
                graphics += ' {} w'.format(round(self.last_stroke_width, 3))

            graphics += ' {} {} m {} {} l S'.format(
                round(x, 3), y_u, round(x + part_width, 3), y_u
            )

        return graphics

class PDFText(PDFTextBase):
    def __init__(
        self, content, width, height, x=0, y=0, fonts=None, text_align=None,
        line_height=None, indent=0, list_text=None, list_indent=0,
        list_style=None, pdf=None
    ):
        self.pdf = pdf
        self.fonts = STANDARD_FONTS if fonts is None else fonts
        self.content = []
        self._recursive_content_parse(content, TEXT_DEFAULTS, [])
        super().__init__(
            self.content, width, height, x, y, fonts, text_align, line_height,
            indent, list_text, list_indent, list_style
        )

    def _new_text_part(self, style, ids, last_part=None):
        if last_part is not None and last_part['text'] == '':
            self.content.remove(last_part)
        text_part = {'style': style, 'text': '', 'ids': ids}
        self.content.append(text_part)
        return text_part

    def _recursive_content_parse(self, content, parent_style, ids):
        style = deepcopy(parent_style)
        ids = deepcopy(ids)

        if isinstance(content, str):
            content = {'.': [content]}
        elif isinstance(content, (list, tuple)):
            content = {'.': content}

        if not isinstance(content, dict):
            raise TypeError(
                'content must be of type dict, str, list or tuple: {}'
                .format(content)
            )

        if len(content) == 1 and 'var' in content and self.pdf:
            content = {'.': [str(self.pdf.context.get(content['var'], ''))]} 

        elements = []
        for key, value in content.items():
            if key.startswith('.'):
                style.update(parse_style_str(key[1:], self.fonts))
                if isinstance(value, str):
                    value = [value]
                if not isinstance(value, (list, tuple)):
                    raise TypeError(
                        'value of . attr must be of type str, list or tuple: {}'
                        .format(value)
                    )
                elements = value
                break

        style.update(process_style(content.get('style'), self.pdf))

        text_part = self._new_text_part(style, ids)

        label = content.get('label', None)
        if label is not None:
            text_part['ids'].append('$label:' + label)
        ref = content.get('ref', None)
        if ref is not None:
            text_part['ids'].append('$ref:' + ref)
        uri = content.get('uri', None)
        if uri is not None:
            text_part['ids'].append('$uri:' + uri)

        is_last_string = False

        for element in elements:
            if isinstance(element, str) and element != '':
                lines = element.split('\n')
                if not is_last_string:
                    text_part = self._new_text_part(
                        style, text_part['ids'], text_part
                    )
                text_part['text'] += lines[0]
                for line in lines[1:]:
                    self.elements.append({'type': 'br'})
                    text_part = self._new_text_part(style, label, ref, uri)
                    text_part['text'] += line
                is_last_string = True
            elif isinstance(element, dict):
                self._recursive_content_parse(element, style, text_part['ids'])
                is_last_string = False
            else:
                raise TypeError(
                    'elements must be of type str or dict: {}'.format(element)
                )

        if text_part is not None and text_part['text'] == '':
            self.content.remove(text_part)

        return False

