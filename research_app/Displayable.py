#   Copyright 2019 APriori Investments
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import object_database.web.cells as cells
import types

from typed_python import Alternative, OneOf, TupleOf, NamedTuple, ConstDict

def raising(type, msg):
    raise type(msg)

Display = lambda: Display
Display = Alternative("Display",
    Displays={'displays': TupleOf(Display), 'title': str},
    Plot={'args': TupleOf(object), 'kwargs': ConstDict(str, object), 'title': str},
    Object={'object': object, 'title': str}, # show an arbitrary python object (should be small - a class or module)
    Print={'str': str, 'title': str}, # show a message from the code.

    titled=lambda self, title:
        Display.Displays(displays=self.displays, title=title) if self.matches.Displays else
        Display.Object(object=self.object, title=title) if self.matches.Object else
        Display.Print(str=self.str, title=title) if self.matches.Print else
        None,

    __add__=lambda self, other:
        Display.Displays(displays=self.displays + other.displays, title=self.title if not other.title else other.title)
            if self.matches.Displays and other.matches.Displays
        else raising(TypeError, f"Can't add {type(self)} and {type(other)}")
    )

@cells.registerDisplay(Display.Print)
def displayForPrint(display):
    return cells.Card(
        cells.Subscribed(lambda:
            cells.Code(display.str)
                .tagged("DatasetDisplay")
            ),
        header=display.title or None
        )

@cells.registerDisplay(Display.Object)
def displayForObject(display):
    obj = display.object

    if isinstance(obj, types.ModuleType):
        return cells.Card(f"Module {obj.__name__}", header=display.title or None)
    if isinstance(obj, types.FunctionType):
        return cells.Card(f"Function {obj.__qualname__}", header=display.title or None)
    if isinstance(obj, type):
        return cells.Card(f"Type {obj.__qualname__}", header=display.title or None)

    return cells.Card(f"Something else: {obj}", header=display.title or None)

@cells.registerDisplay(Display.Displays)
def displayForDisplay(display):
    allDisplays = cells.Sequence(list(display.displays))

    result = cells.Card(
        allDisplays,
        header=display.title if display.title else None
        )

    return result
