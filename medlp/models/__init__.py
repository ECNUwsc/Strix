import os, time
from types import SimpleNamespace as sn
from pathlib import Path
from utils_cw import check_dir
import numpy as np

import torch
from utils_cw.utils import get_items_from_file
from medlp.models.cnn.utils import print_network, output_onehot_transform, PolynomialLRDecay
from medlp.models.cnn.losses.losses import DeepSupervisionLoss, CEDiceLoss, FocalDiceLoss
from medlp.models.cnn.layers.radam import RAdam
from medlp.models.cnn.engines import TRAIN_ENGINES, TEST_ENGINES, ENSEMBLE_TEST_ENGINES
from medlp.models.cnn import ARCHI_MAPPING
#from medlp.models.rcnn.modeling.detector.generalized_rcnn import GeneralizedRCNN
from medlp.utilities.handlers import NNIReporterHandler
from medlp.utilities.enum import RCNN_MODEL_TYPES

from monai_ex.networks.nets import UNet, HighResNet, VNet
from monai_ex.losses import DiceLoss, GeneralizedDiceLoss, FocalLoss
from monai_ex.utils import Activation, ChannelMatching, Normalisation


def get_rcnn_config(archi, backbone):
    folder = Path(__file__).parent.parent.joinpath('misc/config')
    return {
        'mask_rcnn': {
            'R-50-C4': folder/'e2e_mask_rcnn_R_50_C4_1x.yaml',
            'R-50-FPN': folder/'e2e_mask_rcnn_R_50_FPN_1x.yaml',
            'R-101-FPN': folder/'e2e_mask_rcnn_R_101_FPN_1x.yaml'
        },
        'faster_rcnn': {
            'R-50-FPN': folder/'fcos_R_50_FPN_1x.yaml',
            'R-101-FPN': folder/'fcos_R_101_FPN_2x.yaml'
        },
        'fcos': {
            'R-50-C4': folder/'e2e_mask_rcnn_R_50_C4_1x.yaml',
            'R-50-FPN': folder/'e2e_mask_rcnn_R_50_FPN_1x.yaml',
            'R-101-FPN': folder/'e2e_mask_rcnn_R_101_FPN_1x.yaml'
        },
        'retina':{
            'R-50-FPN': folder/'retinanet_R-50-FPN_1x.yaml',
            'R-101-FPN': folder/'retinanet_R-101-FPN_1x.yaml'
        }
    }[archi][backbone]

def get_attr_(obj, name, default):
    return getattr(obj, name) if hasattr(obj, name) else default

def create_feature_maps(init_channel_number, number_of_fmaps):
    return [init_channel_number * 2 ** k for k in range(number_of_fmaps)]

def get_network(opts):
    assert hasattr(opts, 'model_name') and hasattr(opts, 'input_nc') and \
           hasattr(opts, 'tensor_dim') and hasattr(opts, 'output_nc')

    model_name = opts.model_name
    in_channels, out_channels = opts.input_nc, opts.output_nc
    is_deconv = get_attr_(opts, 'is_deconv', False)
    n_depth = get_attr_(opts, 'n_depth', -1)
    load_imagenet = get_attr_(opts, 'load_imagenet', False)
    crop_size = get_attr_(opts, 'crop_size', (512, 512))
    image_size = get_attr_(opts, 'image_size', (512, 512))
    layer_norm = get_attr_(opts, 'layer_norm', 'batch')
    is_prunable = get_attr_(opts, 'snip', False)
    bottleneck_size = get_attr_(opts, 'bottleneck_size', 7)
    # f_maps = get_attr_(opts, 'n_features', 64)
    # skip_conn  = get_attr_(opts, 'skip_conn', 'concat')
    # n_groups = get_attr_(opts, 'n_groups', 8)
    # layer_order = get_attr_(opts, 'layer_order', 'crb')

    model = ARCHI_MAPPING[opts.framework][opts.tensor_dim][opts.model_name]

    dim = 2 if opts.tensor_dim == '2D' else 3
    input_size = image_size if crop_size is None or \
                 np.any(np.less_equal(crop_size, 0)) else crop_size

    if model_name == 'unet' or model_name == 'res-unet':
        last_act = 'sigmoid' if opts.framework == 'selflearning' else None
        n_depth = 5 if n_depth == -1 else n_depth
        kernel_size = (3,)+(3,)*n_depth
        strides = (1,)+(2,)*n_depth
        upsample_kernel_size=(1,)+(2,)*n_depth

        model = model(
            spatial_dims=dim,
            in_channels=in_channels,
            out_channels=out_channels,
            norm_name=layer_norm,
            kernel_size=kernel_size,
            strides=strides,
            upsample_kernel_size=upsample_kernel_size,
            deep_supervision=get_attr_(opts, 'deep_supervision', False),
            deep_supr_num=get_attr_(opts, 'deep_supr_num', 1),
            res_block=(model_name=='res-unet'),
            last_activation=last_act,
            is_prunable=is_prunable
        )
    elif model_name == 'unetv2' or model_name == 'res-unetv2':
        init_feat = get_attr_(opts, 'n_features', 64)
        n_depth = 5 if n_depth == -1 else n_depth
        strides = (2,)*(n_depth-1)
        upsample_kernel_size=(1,)+(2,)*n_depth
        channels = create_feature_maps(init_feat, n_depth)

        model = model(
            dimensions=dim,
            in_channels=in_channels,
            out_channels=out_channels,
            channels=channels,
            strides=strides,
            kernel_size=3,
            up_kernel_size=3,
            num_res_units=2 if model_name=='res-unet' else 0,
            act='prelu',
            norm=layer_norm,
            dropout=0,
        )
    elif model_name == 'highresnet':
        model = model(
            spatial_dims=dim,
            in_channels=in_channels,
            out_channels=out_channels,
            norm_type=layer_norm,
            acti_type=Activation.RELU,
            dropout_prob=0.5,
        )
    elif model_name == 'scnn':
        model = model(
            in_channels=in_channels,
            out_channels=out_channels,
            input_size=input_size,
            ms_ks=9,
            is_deconv=is_deconv,
            use_dilated_conv=True,
            pretrained=load_imagenet)
    elif 'vgg' in model_name:
        model = model(pretrained=load_imagenet,
                      in_channels=in_channels,
                      num_classes=out_channels,
                      dim=dim,
                      is_prunable=is_prunable,
                      bottleneck_size=bottleneck_size)
    elif 'resnet' in model_name or \
         'WRN' in model_name or \
         'resnext' in model_name:
        model = model(pretrained=load_imagenet,
                      in_channels=in_channels,
                      num_classes=out_channels)
    elif model_name == 'vnet':
        model = model(
            spatial_dims=dim,
            in_channels=in_channels,
            out_channels=out_channels,
            act=("leakyrelu", {"inplace": True}),
            dropout_prob=0.5,
            dropout_dim=dim,
        )
    elif model_name == 'ild_net':
        model = model(
            in_channels=in_channels,
            out_channels=out_channels,
            n_depth=5,
            k=4,
            feature_policy='proportional',
            dim=dim,
            is_prunable=is_prunable,
        )
    elif model_name in RCNN_MODEL_TYPES:
        raise NotImplementedError
        # config_file = get_rcnn_config(model_name, opts.backbone)
        # assert config_file.is_file(), f'RCNN config file not exists! {config_file}'
        # config_content = get_items_from_file(config_file, format='yaml')
        # model = GeneralizedRCNN(config_content)
    else:
        raise ValueError(f'Model {model_name} not available')

    return model


def get_engine(opts, train_loader, test_loader, writer=None):
    """Generate engines for specified config.

    Args:
        opts (SimpleNamespace): All arguments from cmd line.
        train_loader (DataLoader): Pytorch dataload for training dataset.
        test_loader (DataLoader): Pytorch dataload for validation dataset.
        writer (SummaryWriter, optional): Tensorboard SummaryWriter. Defaults to None.

    Raises:
        NotImplementedError: Raise error if using undefined loss function.
        NotImplementedError: Raise error if using undefined optim function.

    Returns:
        list: Return engine, net, loss
    """
    # Print the model type
    print('\nInitialising model {}'.format(opts.model_name))
    weight_decay = get_attr_(opts, 'l2_weight_decay', 0.0)
    valid_interval = get_attr_(opts, 'valid_interval', 5)

    framework_type = opts.framework
    device = torch.device("cuda") if opts.gpus != '-1' else torch.device("cpu")
    model_dir = check_dir(opts.experiment_path, 'Models')

    loss = lr_scheduler = None
    if opts.criterion == 'CE':
        loss = torch.nn.CrossEntropyLoss()
    elif opts.criterion == 'WCE':
        w_ = torch.tensor(opts.loss_params).to(device)
        loss = torch.nn.CrossEntropyLoss(weight=w_)
    elif opts.criterion == 'BCE':
        loss = torch.nn.BCEWithLogitsLoss()
    elif opts.criterion == 'WBCE':
        w_ = torch.tensor(opts.loss_params[1]).to(device)
        loss = torch.nn.BCEWithLogitsLoss(pos_weight=w_)
    elif opts.criterion == 'MSE':
        loss = torch.nn.MSELoss()
    elif opts.criterion == 'DCE':
        if opts.output_nc == 1:
            loss = DiceLoss(include_background=False, to_onehot_y=False, sigmoid=True)
        else:
            loss = DiceLoss(include_background=False, to_onehot_y=True, softmax=True)
    elif opts.criterion == 'GDL':
        if opts.output_nc == 1:
            loss = GeneralizedDiceLoss(include_background=False, to_onehot_y=False, sigmoid=True)
        else:
            loss = GeneralizedDiceLoss(include_background=False, to_onehot_y=True, softmax=True)
    elif opts.criterion == 'CE-DCE':
        loss = CEDiceLoss(torch.nn.CrossEntropyLoss(),
                          DiceLoss(include_background=False, to_onehot_y=True, softmax=True))
    elif opts.criterion == 'WCE-DCE':
        w_ = torch.tensor(opts.loss_params).to(device)
        loss = CEDiceLoss(torch.nn.CrossEntropyLoss(weight=w_),
                          DiceLoss(include_background=False, to_onehot_y=True, softmax=True))
    elif opts.criterion == 'Wassert-DCE':
        raise NotImplementedError
    elif opts.criterion == 'FocalLoss':
        loss = FocalLoss(gamma=2.0, weight=None)
    elif opts.criterion == 'FocalDiceLoss':
        loss = FocalDiceLoss(FocalLoss(gamma=2.0),
                             DiceLoss(include_background=False, to_onehot_y=True, softmax=True))
    else:
        raise NotImplementedError

    if opts.deep_supervision:
        loss = DeepSupervisionLoss(loss)

    net_ = get_network(opts)

    if len(opts.gpu_ids) > 1:  # and not opts.amp:
        net = torch.nn.DataParallel(net_.to(device))
    else:
        net = net_.to(device)

    if opts.visualize:
        print_network(net)

    if opts.optim == 'adam':
        optim = torch.optim.Adam(net.parameters(), opts.lr, weight_decay=weight_decay)
    elif opts.optim == 'sgd':
        optim = torch.optim.SGD(net.parameters(), opts.lr, weight_decay=weight_decay)
    elif opts.optim == 'adamw':
        optim = torch.optim.AdamW(net.parameters(), opts.lr, weight_decay=weight_decay)
    elif opts.optim == 'adagrad':
        optim = torch.optim.Adagrad(net.parameters(), opts.lr, weight_decay=weight_decay)
    elif opts.optim == 'radam':
        optim = RAdam(net.parameters(), opts.lr, weight_decay=weight_decay)
    else:
        raise NotImplementedError

    if opts.lr_policy == 'const':
        lr_scheduler = torch.optim.lr_scheduler.LambdaLR(optim, lr_lambda=lambda x:1)
    elif opts.lr_policy == 'poly':
        lr_scheduler = PolynomialLRDecay(optim, opts.n_epoch, end_learning_rate=opts.lr*0.1, power=0.9)
    elif opts.lr_policy == 'step':
        lr_scheduler = torch.optim.lr_scheduler.StepLR(optim, **opts.lr_policy_params)
    elif opts.lr_policy == 'multistep':
        lr_scheduler = torch.optim.lr_scheduler.MultiStepLR(optim,  **opts.lr_policy_params)
    elif opts.lr_policy == 'plateau':
        lr_scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optim,
                                                                  mode='max',
                                                                  factor=0.1,
                                                                  patience=opts.lr_policy_params['patience'],
                                                                  cooldown=50,
                                                                  min_lr=1e-5)
    elif opts.lr_policy == 'SGDR':
        lr_scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(optim,
                                                                            T_0=opts.lr_policy_params['T_0'],
                                                                            T_mult=opts.lr_policy_params['T_mult'],
                                                                            eta_min=opts.lr_policy_params['eta_min'])
    else:
        raise NotImplementedError

    params = {
        'opts': opts,
        'train_loader': train_loader,
        'test_loader': test_loader,
        'net': net,
        'optim': optim,
        'loss': loss,
        'lr_scheduler': lr_scheduler,
        'writer': writer,
        'valid_interval': valid_interval,
        'device': device,
        'model_dir': model_dir,
        'logger_name': f'{opts.tensor_dim}-Trainer'
    }

    engine = TRAIN_ENGINES[framework_type](**params)

    return engine, net


def get_test_engine(opts, test_loader):
    """Generate engine for testing.

    Args:
        opts (SimpleNamespace): All arguments from cmd line.
        test_loader (DataLoader): Pytorch dataload for test dataset.

    Returns:
        IgniteEngine: Return test engine.
    """

    framework_type = opts.framework
    device = torch.device("cuda:0") if opts.gpus != '-1' else torch.device("cpu")

    net = get_network(opts).to(device)

    params = {
        'opts': opts,
        'test_loader': test_loader,
        'net': net,
        'device': device,
        'logger_name': f'{opts.tensor_dim}-Tester'
    }

    if get_attr_(opts, 'n_fold', 0) > 1:
        return ENSEMBLE_TEST_ENGINES[framework_type](**params)
    else:
        return TEST_ENGINES[framework_type](**params)
