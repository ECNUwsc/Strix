import os, time, click
from utils_cw import Print, check_dir, prompt_when, recursive_glob
from functools import partial, wraps

def get_trained_models(exp_folder):
    model_dir = os.path.join(exp_folder,'Models')
    assert os.path.isdir(model_dir), f"Model dir is not found! {model_dir}"
    files = recursive_glob(model_dir, '*.pth')
    prompt = { i:f.stem.split('=')[-1] for i, f in enumerate(files)}
    selected = click.prompt(f"Choose model: {prompt}", type=int)
    return str(files[selected])


def get_exp_name(ctx, param, value):
    if 'debug' in ctx.params and ctx.params['debug']:
        ctx.params['preload'] = 0.0 #emmm...
        return check_dir(ctx.params['out_dir'], 'test')

    model_name = ctx.params['model_type']
    datalist_name = str(ctx.params['data_list'])
    partial_data = '-partial' if 'partial' in ctx.params and ctx.params['partial'] < 1 else ''

    input_size = ctx.params['image_size'] if ctx.params['crop_size'] == (0,0) else ctx.params['crop_size']
    input_size_str = str(input_size).strip('(').strip(')').replace(' ','')

    exp_name = f"{model_name}-{input_size_str}-{ctx.params['criterion'].split('_')[0]}-"\
                f"{ctx.params['optim']}-{ctx.params['lr_policy']}{partial_data}-{ctx.params['timestamp']}"

    #suffix = '-redo' if ctx.params.get('config') is not None else ''
        
    input_str = click.prompt('Experiment name', default=exp_name, type=str)
    exp_name = exp_name + '-' + input_str.strip('+') if '+' in input_str else input_str

    return os.path.join(ctx.params['out_dir'], ctx.params['framework'], datalist_name, exp_name)

def split_input_str(value):
    return [ float(s) for s in value.split(',')] if value is not None else None

def _prompt(prompt_str, data_type, default_value, value_proc=None):
    return click.prompt('\tInput {}'.format(prompt_str),\
                            type=data_type, default=default_value, value_proc=value_proc)

def lr_schedule_params(ctx, param, value):
    if ctx.params.get('lr_policy_params', None) is not None: #loaded config from specified file
        return value

    if value == 'step':
        iters = _prompt('step iter', int, 50) 
        gamma = _prompt('step gamma', float, 0.1)
        ctx.params['lr_policy_params'] = {'step_size':iters, 'gamma':gamma}
    elif value == 'SGDR':
        t0 = _prompt('SGDR T-0', int, 50)
        eta  = _prompt('SGDR Min LR', float, 1e-4)
        tmul = _prompt('SGDR T-mult', int, 1)
        #dcay = _prompt('SGDR decay', float, 1)
        ctx.params['lr_policy_params'] = {'T_0':t0, 'eta_min':eta, 'T_mult':tmul}
    elif value == 'CLR':
        raise NotImplementedError

    return value

def loss_params(ctx, param, value):
    # if ctx.params.get('loss_params', (0,0)) is not (0,0): #loaded config from specified file
    #     return value

    if value == 'WCE':
        weights = _prompt('Loss weights', tuple, (0.01,1), split_input_str)
        ctx.params['loss_params'] = weights
    return value

def model_select(ctx, param, value):
    if value in ['vgg13', 'vgg16', 'resnet34','resnet50']:
        ctx.params['load_imagenet'] = click.confirm("Whether load pretrained ImageNet model?", default=False, abort=False, show_default=True)
        if ctx.params['load_imagenet']:
            ctx.params['input_nc'] = 3
    elif value == 'unet':
        ctx.params['deep_supervision'] = click.confirm("Whether use deep supervision?", default=False, abort=False, show_default=True)
        if ctx.params['deep_supervision']:
            ctx.params['deep_supr_num'] = click.prompt("Num of deep supervision?", default=1, type=int, show_default=True)
    else:
        pass

    return value

DATASET_LIST = ['picc_h5', 'Obj_CXR', 'NIH_CXR', 'rib']
MODEL_TYPES = ['unet', 'res-unet', 'vgg13', 'vgg16', 'resnet34','resnet50','scnn','highresnet']
NORM_TYPES = ['batch','instance','group','auto']
LOSSES = ['CE', 'WCE', 'MSE', 'DCE']
LR_SCHEDULE = ['const', 'lambda', 'step', 'SGDR', 'plateau']
FRAMEWORK_TYPES = ['segmentation','classification','siamese','selflearning','detection']
LAYER_ORDERS = ['crb','cbr', 'cgr','cbe','cB']
OPTIM_TYPES = ['sgd', 'adam']

def common_params(func):
    @click.option('--data-list', prompt=True, type=click.Choice(DATASET_LIST,show_index=True), default=0, help='Data file list (json)')
    @click.option('--framework', prompt=True, type=click.Choice(FRAMEWORK_TYPES,show_index=True), default=1, help='Choose your framework type')
    @click.option('--preload', type=float, default=1.0, help='Ratio of preload data')
    @click.option('--n-epoch', prompt=True, show_default=True, type=int, default=5000, help='Epoch number')
    @click.option('--n-epoch-len', type=int, default=None, help='Num of iterations for one epoch')
    @click.option('--n-batch', prompt=True, show_default=True, type=int, default=50, help='Batch size')
    @click.option('--istrain', type=bool, default=True, help="train/test phase flag")
    @click.option('--downsample', type=int, default=-1, help='Downsample rate. disable:-1')
    @click.option('--smooth', type=float, default=0, help='Smooth rate, disable:0')
    @click.option('--input-nc', type=int, default=1, help='input data channels')
    @click.option('--output-nc', type=int, default=3, help='output channels (classes)')
    @click.option('--tensor-dim', type=str, default='2D', help='2D or 3D')
    @click.option('--split', type=float, default=0.1, help='Training/testing split ratio')
    @click.option('-W', '--pretrained-model-path', type=str, default='', help='pretrained model path')
    @click.option('--out-dir', type=str, prompt=True, show_default=True, default='/homes/clwang/Data/picc/exp')
    @click.option('--augment-ratio', type=float, default=0.3, help='Data aug ratio.')
    @click.option('-P', '--partial', type=float, default=1, callback=partial(prompt_when,trigger='debug'), help='Only load part of data')
    @click.option('-V', '--visualize', is_flag=True, help='Visualize the network architecture')
    @click.option('--save-epoch-freq', type=int, default=5, help='Save model freq')
    @click.option('--seed', type=int, default=101, help='random seed')
    @click.option('--verbose-log', is_flag=True, help='Output verbose log info')
    @click.option('--timestamp', type=str, default=time.strftime("%m%d_%H%M"), help='Timestamp')
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

def network_params(func):
    @click.option('--model-type', prompt=True, type=click.Choice(MODEL_TYPES,show_index=True), callback=model_select, default=1, help='Choose model type')
    @click.option('-L', '--criterion', prompt=True, type=click.Choice(LOSSES,show_index=True), callback=loss_params, default=0, help='loss criterion type')
    @click.option('--image-size', prompt=True, show_default=True, type=(int,int), default=(0,0), help='Input Image size')
    @click.option('--crop-size', prompt=True, show_default=True, type=(int,int), default=(0,0), help='Crop patch size')
    @click.option('--layer-norm', prompt=True, type=click.Choice(NORM_TYPES, show_index=True), default=0, help='Layer norm type')
    @click.option('--n-features', type=int, default=64, help='Feature num of first layer')
    @click.option('--n-level', type=int, default=4, help='Network depth')
    @click.option('--is-deconv', type=bool, default=False, help='use deconv or interplate')
    @click.option('--optim', type=click.Choice(OPTIM_TYPES, show_index=True), default=1)
    @click.option('--amp', is_flag=True, help='Flag of using amp. Need pytorch1.6')
    @click.option('-l2', '--l2-reg-weight', type=float, default=0, help='l2 reg weight')
    @click.option('--lr', type=float, default=1e-3, help='learning rate')
    @click.option('--lr-policy', prompt=True, type=click.Choice(LR_SCHEDULE,show_index=True), callback=lr_schedule_params, default=0, help='learning rate strategy')
    @click.option('--feature-scale', type=int, default=4, help='not used')
    #@click.option('--layer-order', prompt=True, type=click.Choice(LAYER_ORDERS,show_index=True), default=0, help='conv layer order')
    # @click.option('--snip', is_flag=True)
    # @click.option('--snip_percent', type=float, default=0.4, callback=partial(prompt_when,trigger='snip'), help='Pruning ratio of wights/channels')
    # @click.option('--bottleneck', type=bool, default=False, help='Use bottlenect achitecture')
    # @click.option('--sep-conv', type=bool, default=False, help='Use Depthwise Separable Convolution')
    # @click.option('--use-apex', is_flag=True, help='Use NVIDIA apex module')
    # @click.option('--use-half', is_flag=True, help='Use half precision')
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

# Put these auxilary params to the top of click.options for 
# successfully loading auxilary params.
def latent_auxilary_params(func):
    @click.option('--lr-policy-params', type=dict, default=None, help='Auxilary params for lr schedule')
    @click.option('--loss-params', type=(float,float), default=(0,0), help='Auxilary params for loss')
    @click.option('--load-imagenet', type=bool, default=False, help='Load pretrain Imagenet for some net')
    @click.option('--deep-supervision', type=bool, default=False, help='Use deep supervision module')
    @click.option('--deep-supr-num', type=int, default=1, help='Num of features will be output')
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper