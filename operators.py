import json
import os
import shutil
import subprocess
import sys

import bpy
from bpy_extras.io_utils import ExportHelper

from .brte.brte import engine
from .brte.brte.converters import BTFConverter

import blendergltf

from . import pman


def update_blender_path():
    try:
        startdir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else None
        user_config = pman.get_user_config(startdir)
        user_config['blender']['last_path'] = bpy.app.binary_path
        pman.write_user_config(user_config)
    except pman.NoConfigError:
        pass


class ExportBam(bpy.types.Operator, ExportHelper):
    """Export to Panda3D's BAM file format"""
    bl_idname = 'panda_engine.export_bam'
    bl_label = 'Export BAM'

    copy_images = bpy.props.BoolProperty(
        default=True,
    )

    skip_up_to_date = bpy.props.BoolProperty(
        default=False,
    )

    # For ExportHelper
    filename_ext = '.bam'
    filter_glob = bpy.props.StringProperty(
        default='*.bam',
        options={'HIDDEN'},
    )

    def _collect_deltas(self):
        """Return the various deltas needed by BTFConverter.convert()"""
        add_delta = {}
        update_delta = {}
        remove_delta = {}
        view_delta = {}

        collections_list = engine.DEFAULT_WATCHLIST + ['actions']

        for collection in [getattr(bpy.data, i) for i in collections_list]:
            collection_name = engine.get_collection_name(collection)
            collection_set = set(collection)
            add_delta[collection_name] = collection_set

        return (add_delta, update_delta, remove_delta, view_delta)

    def execute(self, context):
        try:
            config = pman.get_config(os.path.dirname(bpy.data.filepath) if bpy.data.filepath else None)
        except pman.NoConfigError as e:
            config = None

        try:
            pycmd = pman.get_python_program(config)
        except pman.CouldNotFindPythonError as e:
            self.report({'ERROR'}, e.value)
            return {'CANCELLED'}

        gltf_settings = {
            'images_data_storage': 'COPY' if self.copy_images else 'REFERENCE',
            'nodes_export_hidden': True,
            'ext_export_physics': True,
            'ext_export_actions': True,
            'gltf_output_dir': os.path.dirname(self.filepath),
        }
        collections_list = engine.DEFAULT_WATCHLIST + ['actions']
        scene_delta = {
            cname: list(getattr(bpy.data, cname))
            for cname in collections_list
        }
        data = blendergltf.export_gltf(scene_delta, gltf_settings)

        # Check if we need to convert the file
        try:
            if self.skip_up_to_date and os.stat(bpy.data.filepath).st_mtime <= os.stat(self.filepath).st_mtime:
                print('"{}" is already up-to-date, skipping'.format(self.filepath))
                return {'FINISHED'}
        except FileNotFoundError:
            # The file doesn't exist, so we cannot skip conversion
            pass


        # Now convert the data to bam
        gltf_fname = self.filepath + '.gltf'
        with open(gltf_fname, 'w') as f:
            json.dump(data, f)

        args = [
            pycmd,
            os.path.join(os.path.dirname(__file__), 'converter.py'),
            gltf_fname,
            self.filepath,
        ]

        subprocess.call(args, env=os.environ.copy())
        os.remove(gltf_fname)
        return {'FINISHED'}


class CreateProject(bpy.types.Operator):
    """Setup a new project directory"""
    bl_idname = 'panda_engine.create_project'
    bl_label = 'Create New Project'

    directory = bpy.props.StringProperty(
        name='Project Directory',
        subtype='DIR_PATH',
    )

    switch_dir = bpy.props.BoolProperty(
        name='Switch to directory',
        default=True,
    )

    def execute(self, context):
        pman.create_project(self.directory)

        if self.switch_dir:
            os.chdir(self.directory)

        update_blender_path()

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout

        layout.prop(self, 'switch_dir')

class UpdateProject(bpy.types.Operator):
    """Re-copies any missing project files"""
    bl_idname = 'panda_engine.update_project'
    bl_label = 'Update Project Files'

    def execute(self, context):
        try:
            config = pman.get_config(os.path.dirname(bpy.data.filepath) if bpy.data.filepath else None)
            pman.create_project(pman.get_abs_path(config, ''))
            return {'FINISHED'}
        except pman.PManException as e:
            self.report({'ERROR'}, e.value)
            return {'CANCELLED'}



class SwitchProject(bpy.types.Operator):
    """Switch to an existing project directory"""
    bl_idname = 'panda_engine.switch_project'
    bl_label = 'Switch Project'

    directory = bpy.props.StringProperty(
        name='Project Directory',
        subtype='DIR_PATH',
    )

    def execute(self, context):
        os.chdir(self.directory)

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class BuildProject(bpy.types.Operator):
    """Build the current project"""
    bl_idname = 'panda_engine.build_project'
    bl_label = 'Build Project'

    def execute(self, context):
        try:
            config = pman.get_config(os.path.dirname(bpy.data.filepath) if bpy.data.filepath else None)
            pman.build(config)
            return {'FINISHED'}
        except pman.PManException as e:
            self.report({'ERROR'}, e.value)
            return {'CANCELLED'}


class RunProject(bpy.types.Operator):
    """Run the current project"""
    bl_idname = 'panda_engine.run_project'
    bl_label = 'Run Project'

    def execute(self, context):
        try:
            config = pman.get_config(os.path.dirname(bpy.data.filepath) if bpy.data.filepath else None)
            if config['run']['auto_save']:
                bpy.ops.wm.save_mainfile()
            pman.run(config)
            return {'FINISHED'}
        except pman.PManException as e:
            self.report({'ERROR'}, e.value)
            return {'CANCELLED'}


def menu_func_export(self, context):
    self.layout.operator(ExportBam.bl_idname, text="Panda3D (.bam)")


def register():
    bpy.types.INFO_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.INFO_MT_file_export.remove(menu_func_export)
