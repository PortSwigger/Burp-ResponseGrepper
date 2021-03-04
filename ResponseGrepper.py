"""
Adds a tab to BurpSuite responses to extract the matches of a regular expression

History:
0.2 - Added a default regex ".*canary.*" and made the regex case insensitive
1.0 - Custom tab pane with HTML styling and per-request regex
1.1 - Updated styling and handled multiple spaces
1.1.1 - Minor clean up
1.2 - Replaced HTMLEditorKit with text/html JTextPane, tweaked styles
1.3 - RegEx updatable by pressing Enter
1.4 - Support for dark themes
1.4.1 - Updated dark theme detection
"""
__author__ = "b4dpxl"
__license__ = "GPL"
__version__ = "1.4.1"

import re
import sys
import traceback

from burp import IBurpExtender
from burp import IMessageEditorTabFactory
from burp import IMessageEditorTab
from burp import ITextEditor

# Java imports
from javax import swing
from java.awt import BorderLayout

import json
import os


NAME = "Response Grepper"
TAB_TITLE = "Grep"


def html_encode(text):
    """Produce entities within text."""
    html_escape_table = {
        "&": "&amp;",
        '"': "&quot;",
        ">": "&gt;",
        "<": "&lt;",
    }
    return "".join(html_escape_table.get(c, c) for c in text)


# replace whitespaces with things that HTML will render
def fix_whitespace(text):
    def _replacer(match):
        return " " + "&nbsp;" * (len(match.group(0)) - 1)

    return re.compile(" {2,}").sub(_replacer, text).replace("\t", "&nbsp;"*4)


def fix_exception(func):
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception:
            sys.stderr.write('\n\n*** PYTHON EXCEPTION\n')
            traceback.print_exc(file=sys.stderr)
            raise
    return wrapper


class BurpExtender(IBurpExtender, IMessageEditorTabFactory):

    _callbacks = None
    _helpers = None

    def __init__(self):
        self._dark_mode = False


    def registerExtenderCallbacks(self, callbacks):
        # for error handling
        sys.stdout = callbacks.getStdout()  
        sys.stderr = callbacks.getStderr()

        self._callbacks = callbacks
        self._helpers = callbacks.getHelpers()

        callbacks.setExtensionName(NAME)
        callbacks.registerMessageEditorTabFactory(self)

        self._checkTheme()

    def createNewInstance(self, controller, editable): 
        return ResponseGrepperTab(self, controller, editable)

    def _checkTheme(self):
        laf = swing.UIManager.getLookAndFeel()
        try:
            self._dark_mode = laf.isDark()

        except:
            print("Unable to detect the mode with isDark(), trying fallback")
            # if it's darcula (for old versions of Burp) or the theme name contains "dark".
            self._dark_mode = bool(re.search(r"""\bdark\b""", theme)) or "darcula" in laf.getID().lower()
            
        print("""Theme: "{}"; Dark mode? {}""".format(laf.getID(), str(self._dark_mode)))
        

class ResponseGrepperTab(IMessageEditorTab):

    @fix_exception
    def __init__(self, extender, controller, editable):
        self._extender = extender
        self._currentMessage = None
        self._helpers = extender._helpers
        self.grep_panel = GrepPanel(self)

    def getTabCaption(self):
        return TAB_TITLE

    def getUiComponent(self):
        return self.grep_panel.getComponent()

    @fix_exception
    def isEnabled(self, content, isRequest):
        if not isRequest:
            if content is not None and len(content) > 0:
                return True

        return False

    @fix_exception
    def setMessage(self, content, isRequest):
        self.grep_panel.setEditable(False)
        self._currentMessage = content

        if content is None or isRequest:
            return

        r = self._helpers.analyzeResponse(content)
        msg = content[r.getBodyOffset():].tostring()
        self.grep_panel.setMessage(msg)

    def getMessage(self): 
        return self._currentMessage

    def isModified(self):
        return self.grep_panel.isTextModified()

    def getSelectedData(self):
        return self.grep_panel.getSelectedText()


class GrepPanel(ITextEditor):

    _msg = None
    _rex = None

    @fix_exception
    def __init__(self, parent):
        self._parent = parent
        self._tab = swing.JPanel(BorderLayout())

        box = swing.Box.createHorizontalBox()
        box.add(swing.JLabel("Regular Expression"))
        self._re_box = swing.JTextField(100, actionPerformed=self._update_rex)
        box.add(self._re_box)
        box.add(swing.JButton('Update', actionPerformed=self._update_rex))
        
        box.add(swing.JButton('?', actionPerformed=self._help))

        self._tab.add(box, BorderLayout.NORTH)

        box = swing.Box.createHorizontalBox()
        self.results = swing.JTextPane()  # JEditorPane()
        self.results.setContentType("text/html")
        self.results.setEditable(False)
        self._render("<em>Loading...</em>")

        scroller = swing.JScrollPane(self.results)
        box.add(scroller)
        self._tab.add(box, BorderLayout.CENTER)

    def _help(self, event):
        swing.JOptionPane.showMessageDialog(None, """All matching subgroups will also be extracted. For example, to extract the value between 2 DIV tags: 

<div class='test'>(.*?)</div>

Named groups can also be used INSTEAD (don't mix named and unnamed). For example:

<div class='test'>(?P<tag>.*?)</div>""")

    def getComponent(self):
        return self._tab

    def getSelectedText(self):
        return None

    def getSelectionBounds(self):
        return None

    def getText(self):
        return self._msg

    def setEditable(self, editable):
        return

    def isTextModified(self):
        return False

    def setSearchExpression(self, str):
        return

    @fix_exception
    def setMessage(self, msg):
        self._msg = msg
        self._update()

    def _update_rex(self, event):
        if self._re_box.getText() is None:
            self._rex = None
        else:
            x = self._re_box.getText().strip()
            if len(x):
                self._rex = x
            else:
                self._rex = None
        self._update()

    _styles = [
        r"""
        .error {color: #CC0000 }
        li, b {color: #000000 }
        .result {color: #006600 }
        .inner_group {background-color: #FFFF00; color: #000000;}
        """,
        r"""
        .error {color: #FF0000 }
        li, b {color: #CCCCCC }
        .result {color: #93C763 }
        .inner_group {background: #111111; color: #E9C063;}
        """
    ]

    @fix_exception
    def _render(self, content):
        self.results.setText(
            r"""<html>
            <head>
            <style type="text/css"><!--
                *, code {{font-size: 11pt; }}
                body {{font-family: sans-serif; }}
                {}
                ul {{list-style-type: none; margin-left: 20px;}}     
                li {{padding-bottom: 5px;}}    
            --></style>
            </head>
            <body>{}</body><html>"""
            .format(
                self._styles[self._parent._extender._dark_mode],
                fix_whitespace(content)
            )
        )

    @fix_exception
    def _update(self):

        if self._rex is None:
            self._render("<b class='error'>Regex not set</b>")

        else:
            try:
                if re.search(self._rex, self._msg, re.IGNORECASE):
                    out = "<ol>"
                    res = re.finditer(self._rex, self._msg, re.IGNORECASE)
                    c = 0
                    for m in res:
                        c += 1

                        g = m.groups()
                        ret = ""
                        if len(g):
                            prev_end = m.start(0)
                            for r in range(1, len(g) + 1):
                                s = m.start(r)
                                e = m.end(r)
                                # print(prev_end, s)
                                ret += self._msg[prev_end:s] + "~~@RG@~~" + g[r - 1] + "~~@@RG@@~~"
                                prev_end = e
                            ret += self._msg[prev_end:m.end(0)]
                        else:
                            ret = m.group(0)

                        out += "<li><code class='result'>{}</code>".format(
                            html_encode(ret.strip())
                            .replace("~~@RG@~~", "<code class='inner_group'>")
                            .replace("~~@@RG@@~~", "</code>")
                        )

                        if len(g):
                            if len(m.groupdict()) > 0:
                                out += "<ul>"
                                # named groups
                                for g in m.groupdict():
                                    out += "<li>{}: <code class='result'>{}</code></li>" \
                                        .format(g, html_encode(m.groupdict()[g].strip()))
                                out += "</ul>"

                            else:
                                out += "<ol>"
                                for g in m.groups():
                                    out += "<li><code class='result'>{}</code></li>".format(html_encode(g).strip())
                                out += "</ol>"

                        # else:
                        #     out += "<br />&nbsp;"

                        out += "</li>"

                    out += "</ol>"
                    # print(out)

                    self._render(
                        "<b>Found <em>{}</em> match(es).</b>{}".format(c, out)
                        )

                else:
                    self._render("<b>No Matches for regex.</b>")

            except re.error  as e:
                self._render("""<b class='error'>Error parsing regex: "<code>{}</code>"<b>""".format(str(e)))

