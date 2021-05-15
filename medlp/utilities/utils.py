from __future__ import print_function
from typing import Union

import os
import struct
import pylab
import torch
from pathlib import Path
import socket
from medlp.utilities.enum import NETWORK_TYPES, DIMS, LR_SCHEDULE
from monai_ex.utils import ensure_list
import tensorboard.compat.proto.event_pb2 as event_pb2
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.ticker import ScalarFormatter
import matplotlib.colors as mcolors
import numpy as np


def bbox_3D(img):
    r = np.any(img, axis=(1, 2))
    c = np.any(img, axis=(0, 2))
    z = np.any(img, axis=(0, 1))

    rmin, rmax = np.where(r)[0][[0, -1]]
    cmin, cmax = np.where(c)[0][[0, -1]]
    zmin, zmax = np.where(z)[0][[0, -1]]

    return rmin, rmax, cmin, cmax, zmin, zmax

def bbox_2D(img):
    rows = np.any(img, axis=1)
    cols = np.any(img, axis=0)
    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]

    return rmin, rmax, cmin, cmax


def create_rgb_summary(label):
    num_colors = label.shape[1]

    cm = pylab.get_cmap('gist_rainbow')

    new_label = np.zeros((label.shape[0], label.shape[1], label.shape[2], 3), dtype=np.float32)

    for i in range(num_colors):
        color = cm(1. * i / num_colors)  # color will now be an RGBA tuple
        new_label[:, :, :, 0] += label[:, :, :, i] * color[0]
        new_label[:, :, :, 1] += label[:, :, :, i] * color[1]
        new_label[:, :, :, 2] += label[:, :, :, i] * color[2]

    return new_label

def add_3D_overlay_to_summary(
    data: Union[torch.Tensor, np.ndarray],
    mask: Union[torch.Tensor, np.ndarray],
    writer,
    index: int = 0,
    tag: str = 'output',
    centers=None
):
    data_ = data[index].detach().cpu().numpy() if torch.is_tensor(data) else data[index]
    mask_ = mask[index].detach().cpu().numpy() if torch.is_tensor(mask) else mask[index]
    # binary_volume = np.squeeze(binary_volume)
    # volume_overlay = np.squeeze(volume_overlay)

    if mask_.shape[1] > 1:
        # there are channels
        mask_ = create_rgb_summary(mask_)
        data_ = data_[..., np.newaxis]

    else:
        data_, mask_ = data_[..., np.newaxis], mask_[..., np.newaxis]

    if centers is None:
        center_x = np.argmax(np.sum(np.sum(np.sum(mask_, axis=3, keepdims=True), axis=2, keepdims=True), axis=1, keepdims=True), axis=0)
        center_y = np.argmax(np.sum(np.sum(np.sum(mask_, axis=3, keepdims=True), axis=2, keepdims=True), axis=0, keepdims=True), axis=1)
        center_z = np.argmax(np.sum(np.sum(np.sum(mask_, axis=3, keepdims=True), axis=1, keepdims=True), axis=0, keepdims=True), axis=2)
    else:
        center_x, center_y, center_z = centers

    segmentation_overlay_x = \
        np.squeeze(data_[center_x, :, :, :] + mask_[center_x, :, :, :])
    segmentation_overlay_y = \
        np.squeeze(data_[:, center_y, :, :] + mask_[:, center_y, :, :])
    segmentation_overlay_z = \
        np.squeeze(data_[:, :, center_z, :] + mask_[:, :, center_z, :])

    if len(segmentation_overlay_x.shape) != 3:
        segmentation_overlay_x, segmentation_overlay_y, segmentation_overlay_z = \
            segmentation_overlay_x[..., np.newaxis], \
            segmentation_overlay_y[..., np.newaxis], \
            segmentation_overlay_z[..., np.newaxis]

    writer.add_image(tag + '_x', segmentation_overlay_x)
    writer.add_image(tag + '_y', segmentation_overlay_y)
    writer.add_image(tag + '_z', segmentation_overlay_z)

def add_3D_image_to_summary(manager, image, name, centers=None):
    image = np.squeeze(image)

    if len(image.shape) > 3:
        # there are channels
        print('add_3D_image_to_summary: there are channels')
        image = create_rgb_summary(image)
    else:
        image = image[..., np.newaxis]

    if centers is None:
        center_x = np.argmax(np.sum(np.sum(np.sum(image, axis=3, keepdims=True), axis=2, keepdims=True), axis=1, keepdims=True), axis=0)
        center_y = np.argmax(np.sum(np.sum(np.sum(image, axis=3, keepdims=True), axis=2, keepdims=True), axis=0, keepdims=True), axis=1)
        center_z = np.argmax(np.sum(np.sum(np.sum(image, axis=3, keepdims=True), axis=1, keepdims=True), axis=0, keepdims=True), axis=2)
    else:
        center_x, center_y, center_z = centers

    segmentation_overlay_x = np.squeeze(image[center_x, :, :, :])
    segmentation_overlay_y = np.squeeze(image[:, center_y, :, :])
    segmentation_overlay_z = np.squeeze(image[:, :, center_z, :])

    if len(segmentation_overlay_x.shape) != 3:
        segmentation_overlay_x, segmentation_overlay_y, segmentation_overlay_z = \
            segmentation_overlay_x[..., np.newaxis], \
            segmentation_overlay_y[..., np.newaxis], \
            segmentation_overlay_z[..., np.newaxis]

    manager.add_image(name + '_x', segmentation_overlay_x)
    manager.add_image(name + '_y', segmentation_overlay_y)
    manager.add_image(name + '_z', segmentation_overlay_z)


def output_filename_check(torch_dataset, meta_key='image_meta_dict'):
    if len(torch_dataset) == 1:
        return Path(torch_dataset[0][meta_key]['filename_or_obj']).parent.parent

    prev_data = torch_dataset[0]
    next_data = torch_dataset[1]

    if Path(prev_data[meta_key]['filename_or_obj']).stem != Path(next_data[meta_key]['filename_or_obj']).stem:
        return Path(prev_data[meta_key]['filename_or_obj']).parent

    for i, (prev_v, next_v) in enumerate(zip(Path(prev_data[meta_key]['filename_or_obj']).parents,
                                             Path(next_data[meta_key]['filename_or_obj']).parents)):
        if prev_v.stem != next_v.stem:
            return prev_v.parent

    return ''


def get_attr_(obj, name, default):
    return getattr(obj, name) if hasattr(obj, name) else default


def detect_port(port):
    '''Detect if the port is used'''
    socket_test = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        socket_test.connect(('127.0.0.1', int(port)))
        socket_test.close()
        return True
    except:
        return False

def parse_nested_data(data):
    params = {}
    for key, value in data.items():
        if isinstance(value, dict):
            value_ = value.copy()
            if key == 'lr_policy':
                policy_name = value_.get('_name', None)
                if policy_name in LR_SCHEDULE:
                    params[key] = policy_name
                    value_.pop('_name')
                    params['lr_policy_params'] = value_
            else:
                raise NotImplementedError(f'{key} is not supported for nested params.')
        else:
            params[key] = value
    return params

def get_network_type(name):
    for k, v in NETWORK_TYPES.items():
        if name in v:
            return k

def assert_network_type(model_name, target_type):
    assert get_network_type(model_name) == target_type, f"Only accept {target_type} arch: {NETWORK_TYPES[target_type]}"

def _register_generic(module_dict, module_name, module):
    assert module_name not in module_dict
    module_dict[module_name] = module

def _register_generic_dim(module_dict, dim, module_name, module):
    assert module_name not in module_dict.get(dim), f'{module_name} already registed in {module_dict.get(dim)}'
    module_dict[dim].update({module_name:module})

def _register_generic_data(module_dict, dim, module_name, fpath, module):
    assert module_name not in module_dict.get(dim), f'{module_name} already registed in {module_dict.get(dim)}'
    module_dict[dim].update({module_name:module, module_name+"_fpath":fpath})


def is_avaible_size(value):
    if isinstance(value, (list, tuple)):
        if np.all(np.greater(value, 0)):
            return True
    return False


def plot_summary(summary, output_fpath):
    try:
        f = plt.figure(1)
        plt.clf()
        colors = list(mcolors.TABLEAU_COLORS.values())

        for i, (key, step_value) in enumerate(summary.items()):
            plt.plot(step_value['steps'], step_value['values'], label=key, color=colors[i], linewidth=2.0)
        # plt.ylim([0., 1.])
        ax = plt.axes()
        ax.yaxis.set_major_locator(ticker.MultipleLocator(0.05))
        ax.yaxis.set_major_formatter(ScalarFormatter())
        plt.xlabel('Number of iterations per case')
        plt.grid(True)
        plt.legend()
        plt.draw()
        plt.show(block=False)
        plt.pause(0.0001)
        f.show()

        f.savefig(output_fpath)
    except Exception as e:
        print('Failed to do plot: ' + str(e))

def dump_tensorboard(db_file, dump_keys=None, save_image=False, verbose=False):
    if not os.path.isfile(db_file):
        raise FileNotFoundError(f'db_file is not found: {db_file}')

    if dump_keys is not None:
        dump_keys = ensure_list(dump_keys)

    def _read(input_data):
        header = struct.unpack('Q', input_data[:8])
        # crc_hdr = struct.unpack('I', input_data[:4])
        eventstr = input_data[12:12+int(header[0])]  # 8+4
        out_data = input_data[12+int(header[0])+4:]
        return out_data, eventstr

    with open(db_file, 'rb') as f:
        data = f.read()

    summaries = {}
    while data:
        data, event_str = _read(data)
        event = event_pb2.Event()
        event.ParseFromString(event_str)
        if event.HasField('summary'):
            for value in event.summary.value:
                if value.HasField('simple_value'):
                    if dump_keys is None or value.tag in dump_keys:
                        if not summaries.get(value.tag, None):
                            summaries[value.tag] = {'steps': [event.step], 'values': [value.simple_value]}
                        else:
                            summaries[value.tag]['steps'].append(event.step)
                            summaries[value.tag]['values'].append(value.simple_value)
                        if verbose:
                            print(value.simple_value, value.tag, event.step)
                if value.HasField('image') and save_image:
                    img = value.image
                    # save_img(img.encoded_image_string, event.step, save_gif=args.gif)
    return summaries


class Registry(dict):
    '''
    A helper class for managing registering modules, it extends a dictionary
    and provides a register functions.

    Eg. creeting a registry:
        some_registry = Registry({"default": default_module})

    There're two ways of registering new modules:
    1): normal way is just calling register function:
        def foo():
            ...
        some_registry.register("foo_module", foo)
    2): used as decorator when declaring the module:
        @some_registry.register("foo_module")
        @some_registry.register("foo_modeul_nickname")
        def foo():
            ...

    Access of module is just like using a dictionary, eg:
        f = some_registry["foo_modeul"]
    '''
    def __init__(self, *args, **kwargs):
        super(Registry, self).__init__(*args, **kwargs)

    def register(self, module_name, module=None):
        # used as function call
        if module is not None:
            _register_generic(self, module_name, module)
            return

        # used as decorator
        def register_fn(fn):
            _register_generic(self, module_name, fn)
            return fn

        return register_fn


class DimRegistry(dict):
    def __init__(self, *args, **kwargs):
        super(DimRegistry, self).__init__(*args, **kwargs)
        self.dim_mapping = {'2': '2D', '3': '3D', 2: '2D', 3: '3D', '2D': '2D', '3D': '3D'}
        self['2D'] = {}
        self['3D'] = {}

    def register(self, dim, module_name, module=None):
        assert dim in DIMS, "Only support 2D&3D dataset now"
        dim = self.dim_mapping[dim]
        # used as function call
        if module is not None:
            _register_generic_dim(self, dim, module_name, module)
            return

        # used as decorator
        def register_fn(fn):
            _register_generic_dim(self, dim, module_name, fn)
            return fn 
        return register_fn


class DatasetRegistry(DimRegistry):
    def __init__(self, *args, **kwargs):
        super(DatasetRegistry, self).__init__(*args, **kwargs)

    def register(self, dim, module_name, fpath, module=None):
        assert dim in DIMS, "Only support 2D&3D dataset now"
        dim = self.dim_mapping[dim]
        # used as function call
        if module is not None:
            _register_generic_data(self, dim, module_name, fpath, module)
            return

        # used as decorator
        def register_fn(fn):
            _register_generic_data(self, dim, module_name, fpath, fn)
            return fn 
        return register_fn


