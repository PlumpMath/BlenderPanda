'''OpenGL extension OES.blend_equation_separate

This module customises the behaviour of the 
OpenGL.raw.GLES1.OES.blend_equation_separate to provide a more 
Python-friendly API

The official definition of this extension is available here:
http://www.opengl.org/registry/specs/OES/blend_equation_separate.txt
'''
from OpenGL import platform, constant, arrays
from OpenGL import extensions, wrapper
import ctypes
from OpenGL.raw.GLES1 import _types, _glgets
from OpenGL.raw.GLES1.OES.blend_equation_separate import *
from OpenGL.raw.GLES1.OES.blend_equation_separate import _EXTENSION_NAME

def glInitBlendEquationSeparateOES():
    '''Return boolean indicating whether this extension is available'''
    from OpenGL import extensions
    return extensions.hasGLExtension( _EXTENSION_NAME )


### END AUTOGENERATED SECTION