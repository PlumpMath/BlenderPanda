import ctypes
import json
import math
import os
import socket
import struct
import sys
import time
import threading

try:
    import queue
except ImportError:
    import Queue as queue

from direct.showbase.ShowBase import ShowBase
import panda3d.core as p3d

from converter import Converter


p3d.load_prc_file_data('', 
    'window-type none\n'
    'gl-debug #t\n'
)

USE_THREAD = True

class Server(threading.Thread):
    def __init__(self, data_handler, update_handler):
        super().__init__()
        self.socket = socket.socket()
        self.socket.settimeout(5)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.image_lock = threading.Lock()

        remaining_attempts = 3
        while remaining_attempts:
            try:
                self.socket.connect(('127.0.0.1', 5555))
                break
            except Exception as e:
                print(e)
                time.sleep(1)
                remaining_attempts -= 1
        else:
            print("Unable to connect to Blender")
            sys.exit(-1)

        self.data_handler = data_handler
        self.update_handler = update_handler

    def run(self):
        while True:
            msg_header = self.socket.recv(2)
            msg_id = struct.unpack('=H', msg_header)[0]
            if msg_id == 0:
                data_size = struct.unpack('=I', self.socket.recv(4))[0]
                data = bytearray(data_size)
                view = memoryview(data)
                while len(view) > 0:
                    rcv_size = self.socket.recv_into(view, len(view))
                    view = view[rcv_size:]
                data = json.loads(data.decode('ascii'))

                self.data_handler(data)

                self.socket.send(struct.pack('B', 0))
            elif msg_id == 1:
                start = time.perf_counter()
                dt = struct.unpack('=f', self.socket.recv(4))[0]

                self.image_lock.acquire()
                width, height, img_buffer = self.update_handler(dt)

                #print('Extern: width {}, height {}, len(img_buffer) {}'.format(width, height, len(img_buffer)))
                self.socket.send(struct.pack('=HH', width, height))
                self.socket.sendall(img_buffer)
                self.image_lock.release()
                transfer_t = time.perf_counter() - start
                data_size = width*height*3
                #print('Extern: Update time: {}ms'.format(transfer_t * 1000))
                #print('Extern: Speed: {} Gbit/s'.format(data_size/1024/1024/1024*8 / transfer_t))
            else:
                print('Received unknown message ID: {}'.format(msg_id))
                self.socket.send(struct.pack('=B', 0))

            if not USE_THREAD:
                break


class App(ShowBase):
    def __init__(self, model_dirs):
        ShowBase.__init__(self)
        self.view_lens = p3d.MatrixLens()
        self.view_camera = p3d.NodePath(p3d.Camera('view'))
        self.view_camera.node().set_lens(self.view_lens)
        self.view_camera.node().set_active(True)
        self.view_camera.reparent_to(self.render)

        self.pipe = p3d.GraphicsPipeSelection.get_global_ptr().make_module_pipe('pandagl')

        self.bg = p3d.LVecBase4(0.0, 0.0, 0.0, 1.0)

        for mdir in model_dirs:
            p3d.get_model_path().prepend_directory(mdir)

        self.texture = p3d.Texture()
        self.win = None
        self.make_offscreen(1, 1)

        self.disableMouse()
        self.setFrameRateMeter(True)

        self.image_width = 1
        self.image_height = 1
        self.image_data = struct.pack('=BBB', 0, 0, 0)

        # Setup conversion logic
        self.converter = Converter()
        self.conversion_queue = queue.Queue()
        def conversion(task):
            while not self.conversion_queue.empty():
                data = self.conversion_queue.get()
                #print(data)
                if 'extras' in data and 'view' in data['extras']:
                    viewd = data['extras']['view']
                    if 'width' in viewd:
                        width = viewd['width']
                        height = viewd['height']
                        self.make_offscreen(width, height)
                    if 'projection_matrix' in viewd:
                        proj_mat = self.converter.load_matrix(viewd['projection_matrix'])
                        self.view_lens.set_user_mat(proj_mat)
                    if 'view_matrix' in viewd:
                        view_mat = self.converter.load_matrix(viewd['view_matrix'])

                        # Panda wants an OpenGL model matrix instead of an OpenGL view matrix
                        view_mat.invert_in_place()
                        self.view_lens.set_view_mat(view_mat)

                self.converter.update(data)
                bg = self.converter.background_color
                self.bg = p3d.LVector4(bg[0], bg[1], bg[2], 1)
                self.view_region.set_clear_color(self.bg)
                self.converter.active_scene.reparent_to(self.render)
                #self.render.ls()

            if self.texture.has_ram_image():
                self.server.image_lock.acquire()
                self.image_width = self.texture.get_x_size()
                self.image_height = self.texture.get_y_size()
                self.image_data = memoryview(self.texture.get_ram_image_as("RGB"))
                self.server.image_lock.release()
                #self.texture.write('tex.png')
            return task.cont

        self.taskMgr.add(conversion, 'Conversion')

        # Setup communication with Blender
        self.server = Server(self.handle_data, self.get_img)
        if USE_THREAD:
            self.server.start()
            def server_mon(task):
                if not self.server.is_alive():
                    print('Server thread has terminated, closing program')
                    sys.exit()
                return task.cont
            self.taskMgr.add(server_mon, 'Server Monitor')
        else:
            def server_task(task):
                self.server.run()
                return task.cont
            self.taskMgr.add(server_task, 'Server Communication')

    def make_offscreen(self, sx, sy):
        #sx = p3d.Texture.up_to_power_2(sx)
        #sy = p3d.Texture.up_to_power_2(sy)

        if self.win and self.win.get_size()[0] == sx and self.win.get_size()[1] == sy:
            # The current window is good, don't waste time making a new one
            return

        use_frame_rate_meter = self.frameRateMeter is not None
        self.setFrameRateMeter(False)

        self.graphicsEngine.remove_all_windows()
        self.win = None
        self.view_region = None

        fbprops = p3d.FrameBufferProperties()
        fbprops.set_srgb_color(True)
        fbprops.set_rgba_bits(8, 8, 8, 0)
        fbprops.set_depth_bits(24)
        wp = p3d.WindowProperties.size(sx, sy)
        flags = p3d.GraphicsPipe.BF_refuse_window
        #flags = p3d.GraphicsPipe.BF_require_window
        self.win = self.graphicsEngine.make_output(
                self.pipe,
                'window',
                0,
                fbprops,
                wp,
                flags
        )

        dr = self.win.make_mono_display_region()
        dr.set_camera(self.view_camera)
        dr.set_active(True)
        dr.set_clear_color_active(True)
        dr.set_clear_color(self.bg)
        dr.set_clear_depth(1.0)
        dr.set_clear_depth_active(True)
        self.view_region = dr
        self.graphicsEngine.open_windows()

        self.setFrameRateMeter(use_frame_rate_meter)

        self.texture = p3d.Texture()
        self.win.addRenderTexture(self.texture, p3d.GraphicsOutput.RTM_copy_ram)

    def handle_data(self, data):
        self.conversion_queue.put(data)

    def get_img(self, dt):
        return self.image_width, self.image_height, self.image_data


if __name__ == "__main__":
    model_dirs = []
    if len(sys.argv) > 1 and sys.argv[1]:
        model_dirs.append(sys.argv[1])
    app = App(model_dirs)
    app.run()