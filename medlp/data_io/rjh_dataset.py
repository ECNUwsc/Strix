import os, sys, time, torch, random, tqdm, math
import numpy as np
from utils_cw import Print, load_h5
import nibabel as nib

from typing import Any, Callable, Dict, Hashable, List, Mapping, Optional, Sequence, Tuple, Union
from medlp.data_io.base_dataset.selflearning_dataset import SelflearningDataset3D
from medlp.data_io.base_dataset.segmentation_dataset import SegmentationDataset3D
from medlp.data_io.base_dataset.classification_dataset import ClassificationDataset3D
from medlp.utilities.utils import is_avaible_size
from medlp.utilities.transforms import LabelMorphologyD, DataLabellingD

import monai
from monai.config import IndexSelection, KeysCollection
from monai.data import CacheDataset, Dataset, PersistentDataset
from monai.utils import Method, NumpyPadMode, ensure_tuple, ensure_tuple_rep, fall_back_tuple, InterpolateMode
from monai.transforms.utils import generate_pos_neg_label_crop_centers
from monai.transforms import *

def get_rjh_tswi_sl_dataset(
    files_list,
    phase,
    spacing=None,
    winlevel=[-80,304],
    in_channels=1,
    image_size=None,
    crop_size=None, 
    preload=1.0, 
    augment_ratio=0.4, 
    downsample=1, 
    orientation='LPI',
    cache_dir='./',
    verbose=False
):
    if phase == 'train' or phase == 'valid':
        dataset = SelflearningDataset3D(
            files_list,
            repeater=None,
            spacer=None,
            rescaler=ScaleIntensityRanged(keys=["image","label"], a_min=0, a_max=255, b_min=0, b_max=1, clip=True),
            resizer=None,
            cropper=RandSpatialCropd(keys=["image", "label"], roi_size=(96,96,96), random_size=False),
            
        )
    
    return

#win width: 1130.0, 19699.0
def get_rjh_tswi_seg_dataset(
    files_list,
    phase,
    spacing=(0.667,0.667,1.34),
    winlevel=(1130.0, 19699.0),
    in_channels=1,
    crop_size=(96,96,64),
    preload=0,
    augment_ratio=0.4,
    orientation='RAI',
    cache_dir='./',
    verbose=False
):
    assert in_channels == 1, 'Currently only support single channel input'

    cropper = RandCropByPosNegLabeld(keys=["image","label"], label_key='label', pos=1, neg=1, spatial_size=crop_size) if \
              is_avaible_size(crop_size) else None
    if phase == 'train':
        additional_transforms = [
            RandFlipD(keys=["image","label"], prob=augment_ratio, spatial_axis=[2]),
            RandRotateD(keys=["image","label"], range_x=math.pi/40, range_y=math.pi/40, range_z=math.pi/40, prob=augment_ratio, padding_mode='zeros'),
            Rand3DElasticD(keys=["image","label"], prob=augment_ratio, sigma_range=(5,10),
                           magnitude_range=(50,150), mode=["bilinear","nearest"], padding_mode='zeros')
        ]
    elif phase == 'valid':
        additional_transforms = []
    elif phase == 'test':
        cropper = None
        additional_transforms = []
    elif phase == 'test_wo_label':
        return SegmentationDataset3D(
                    files_list,
                    loader=LoadNiftid(keys="image", dtype=np.float32),
                    channeler=AddChanneld(keys="image"),
                    orienter=Orientationd(keys='image', axcodes=orientation),
                    spacer=SpacingD(keys="image", pixdim=spacing),
                    resizer=None,
                    rescaler=NormalizeIntensityD(keys='image'),
                    cropper=None,
                    additional_transforms=[],
                    caster=CastToTyped(keys="image", dtype=np.float32),
                    to_tensor=ToTensord(keys="image"),
                    preload=0,
                    cache_dir=cache_dir,
                ).get_dataset()
    else:
        raise ValueError

    dataset = SegmentationDataset3D(
        files_list,
        orienter=Orientationd(keys=['image','label'], axcodes=orientation),
        spacer=SpacingD(keys=["image","label"], pixdim=spacing, mode=[GridSampleMode.BILINEAR,GridSampleMode.NEAREST]),
        resizer=None,
        rescaler=NormalizeIntensityD(keys='image'),
        cropper=cropper,
        additional_transforms=[DataLabellingD(keys='label'), 
                               LabelMorphologyD(keys='label',mode='dilation',radius=1,binary=False)]+additional_transforms,
        preload=preload,
        cache_dir=cache_dir,
    ).get_dataset()

    return dataset


def get_rjh_tswi_cls_dataset(
    files_list,
    phase,
    spacing=(0.667,0.667,1.34),
    winlevel=None,
    in_channels=1,
    crop_size=(96,96,64),
    preload=0,
    augment_ratio=0.4,
    orientation='RAI',
    cache_dir='./',
    verbose=False
):
    assert in_channels == 1, 'Currently only support single channel input'
    
    dataset = ClassificationDataset3D(
        files_list,
        orienter=Orientationd(keys=['image','label'], axcodes=orientation),
        spacer=SpacingD(keys=["image","label"], pixdim=spacing, mode=[GridSampleMode.BILINEAR,GridSampleMode.NEAREST]),
        resizer=None,
        rescaler=NormalizeIntensityD(keys='image'),
        cropper=cropper,
        additional_transforms=additional_transforms,
        preload=preload,
        cache_dir=cache_dir,
    ).get_dataset()

    return dataset