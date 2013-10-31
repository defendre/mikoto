# -*- coding: utf-8 -*-

from __future__ import absolute_import
import re
import misaka
import chardet

from cgi import escape
from pygments.formatters import HtmlFormatter
from pygments.lexers import (TextLexer, get_lexer_by_name,
                             guess_lexer_for_filename, MakoHtmlLexer, PythonLexer, RstLexer)
from pygments.util import ClassNotFound
from pygments import highlight

try:
    import docutils, docutils.core
except ImportError:
    print "Did not install docutils"

from mikoto.libs.consts import (SOURCE_FILE, NOT_GENERATED,
                                IGNORE_FILE_EXTS, IS_GENERATED)
from mikoto.libs.emoji import parse_emoji


RST_RE = re.compile(r'.*\.re?st(\.txt)?$')
RE_TICKET = re.compile(r'(?:^|\s)#(\d+)')
RE_USER_MENTION = re.compile('(^|\W)@([a-zA-Z0-9_]+)')
RE_COMMIT = re.compile(r'(^|\s)([0-9a-f]{7,40})')
RE_IMAGE_FILENAME = re.compile(
    r'^.+\.(?:jpg|png|gif|jpeg|mobileprovision|svg|ico)$', flags=re.IGNORECASE)
RE_CHECKBOX_IN_HTML = re.compile('<li>\[[x\s]\].+</li>')
RE_CHECKBOX_IN_TEXT = re.compile('- (\[[x\s]\]).+')

CHECKED = '[x]'
UNCHECKED = '[ ]'
HTML_CHECKED = '<li>[x]'
HTML_UNCHECKED = '<li>[ ]'
RE_PR_IN_MESSAGE = re.compile(r'(?:^|\s)#(\d+)(?:\s|$)')

class _CodeHtmlFormatter(HtmlFormatter):
    def wrap(self, source, outfile):
        return self._wrap_div(self._wrap_pre(self._wrap_a_line(source)))

    def _wrap_a_line(self, source):
        for i, t in source:
            if i == 1:
                # it's a line of formatted code
                t = '<div>' + t + '</div>'
            yield i, t


class _CodeRenderer(misaka.HtmlRenderer):
    def postprocess(self, text):
        if not text:
            return text
        text = render_checklist(text)
        text = parse_emoji(text, is_escape=False)
        return RE_USER_MENTION.sub(r'\1<a href="/people/\2/" class="user-mention">@\2</a>', text)

    def block_code(self, text, lang):
        if not lang:
            return '\n<pre><code>%s</code></pre>\n' % escape(text.strip())
        lexer = get_lexer_by_name(lang, stripall=True)
        formatter = HtmlFormatter()
        return highlight(text, lexer, formatter)

    def header(self, text, level):
        if level == 1 and re.match(r'\d+', text):
            return '#' + text
        return '<h%s>%s</h%s>' % (level, text, level)

_generic_renderer = _CodeRenderer(misaka.HTML_HARD_WRAP |
                                  misaka.HTML_SAFELINK |
                                  misaka.HTML_SKIP_STYLE |
                                  misaka.HTML_SKIP_SCRIPT |
                                  misaka.HTML_ESCAPE)
_markdown_renderer = misaka.Markdown(_generic_renderer,
                                     extensions=misaka.EXT_FENCED_CODE |
                                     misaka.EXT_NO_INTRA_EMPHASIS |
                                     misaka.EXT_AUTOLINK |
                                     misaka.EXT_TABLES |
                                     misaka.EXT_STRIKETHROUGH)

def decode_charset_to_unicode(charset, default='utf-8'):
    try:
        return charset.decode(default)
    except UnicodeDecodeError:
        charset_encoding = chardet.detect(charset).get('encoding') or default
        return charset.decode(charset_encoding, 'ignore')


def highlight_code(path, src, div=False, **kwargs):
    src = decode_charset_to_unicode(src)
    try:
        if path.endswith(('.html', '.mako')):
            lexer = MakoHtmlLexer(encoding='utf-8')
        elif path.endswith('.ptl'):
            lexer = PythonLexer(encoding='utf-8')
        elif path.endswith('.md'):
            lexer = RstLexer(encoding='utf-8')
        else:
            if path.endswith(IGNORE_FILE_EXTS):
                src = 'Hmm.., this is binary file.'
            lexer = guess_lexer_for_filename(path, src)
        lexer.encoding = 'utf-8'
        lexer.stripnl = False
    except ClassNotFound:
        # no code highlight
        lexer = TextLexer(encoding='utf-8')
    if div:
        formatter = _CodeHtmlFormatter
    else:
        formatter = HtmlFormatter
    src = highlight(src, lexer, formatter(
        linenos=True, lineanchors='L', anchorlinenos=True, encoding='utf-8', **kwargs))
    return src


def format_md_or_rst(path, src):
    src = decode_charset_to_unicode(src)
    if path.endswith('.md') or path.endswith('.markdown'):
        return render_markdown(src)

    if RST_RE.match(path):
        try:
            return docutils.core.publish_parts(src, writer_name='html')['html_body']
        except docutils.ApplicationError:
            pass

    lexer = TextLexer(encoding='utf-8')
    return highlight(src, lexer, HtmlFormatter(linenos=True, lineanchors='L', anchorlinenos=True, encoding='utf-8'))


def render_checklist(content):
    i = 0
    while 1:
        m = re.search(RE_CHECKBOX_IN_HTML, content)
        if not m:
            break
        t = m.group(0).lstrip('<li>').rstrip('</li>')
        if t.startswith(CHECKED):
            checked_idx = content.find(HTML_CHECKED)
            content = content[:checked_idx] + \
                      '<li><label><input type="checkbox" data-item-index="%d" checked> ' % i + \
                      t.lstrip(CHECKED).strip() + '</label></li>' + \
                      content[checked_idx + len(t) + len('<li>') + len('</li>'):]
        else:
            unchecked_idx = content.find(HTML_UNCHECKED)
            content = content[:unchecked_idx] + \
                      '<li><label><input type="checkbox" data-item-index="%d"> ' % i + \
                      t.lstrip(UNCHECKED).strip() + '</label></li>' + \
                      content[unchecked_idx + len(t) + len('<li>') + len('</li>'):]
        i += 1
    return content


def render_markdown(content):
    if not content:
        content = ''
    return _markdown_renderer.render(content)


def render_markdown_with_project(content, project_name):
    text = render_markdown(content)
    text = re.sub(RE_TICKET, r'<a href="/%s/pull/\1/" class="issue-link">#\1</a>' % project_name, text)
    text = re.sub(RE_COMMIT, r' <a href="/%s/commit/\2">\2</a>' % project_name, text)
    return text

def get_checkbox_count(content):
    m = re.findall(RE_CHECKBOX_IN_TEXT, content)
    if m:
        checked = filter(lambda x:x == CHECKED, m)
        return (len(checked), len(m))

def render_markdown_with_team(content, team):
    text = render_markdown(content)
    text = re.sub(RE_TICKET, r'<a href="' + team.url +
                  r'issues/\1/" class="issue-link">#\1</a>', text)
    return parse_emoji(text, is_escape=False)

def is_binary(fname):
    ext = fname.split('.')
    if ext is None:
        return False
    if len(ext) == 1:
        return ext[0] not in SOURCE_FILE
    ext = '.' + ext[-1]
    if ext in IS_GENERATED:
        return False
    if ext in IGNORE_FILE_EXTS or ext not in (SOURCE_FILE + NOT_GENERATED):
        return True
    return False

def get_mentions_from_text(text):
    try:
        from models.team import Team
    except ImportError:
        from mikoto.libs.mock import Team
    recipients = RE_USER_MENTION.findall(text)
    users = set()
    for _, r in recipients:
        t = Team.get_by_uid(r)
        if t:
            users.update(t.all_members)
        else:
            users.add(r)
    return list(users)

def render_commit_message(message, project):
    text = parse_emoji(message)
    text = re.sub(RE_PR_IN_MESSAGE, r' <a href="/%s/newpull/\1">#\1</a> ' % project.name, text)
    text = text.decode('utf8')
    return text
