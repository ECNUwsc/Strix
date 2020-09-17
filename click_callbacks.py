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
        return check_dir(ctx.params['out_dir'], 'test')

    model_name = ctx.params['model_type']
    datalist_name = str(ctx.params['data_list'])
    if 'partial' in ctx.params and ctx.params['partial'] < 1:
        datalist_name = datalist_name+'_p'

    crop_size_str = str(ctx.params['crop_size']).strip('(').strip(')').replace(' ','')

    exp_name = f"{datalist_name}-{model_name}-{crop_size_str}-{ctx.params['criterion'].split('_')[0]}-"\
                f"{ctx.params['optim']}-{ctx.params['lr_policy']}-{ctx.params['timestamp']}"

    #suffix = '-redo' if ctx.params.get('config') is not None else ''
        
    input_str = click.prompt('Experiment name', default=exp_name, type=str)
    exp_name = exp_name + '-' + input_str.strip('+') if '+' in input_str else input_str

    return os.path.join(ctx.params['out_dir'], ctx.params['framework'], exp_name)

def _prompt(prompt_str, data_type, default_value):
    return click.prompt('\tInput {} for lr strategy'.format(prompt_str),\
                            type=data_type, default=default_value)

def lr_schedule_params(ctx, param, value):
    if ctx.params.get('lr_policy_params', None): #loaded config from specified file
        return value

    if value == 'step':
        iters = _prompt('step iter', int, 50) 
        gamma = _prompt('step gamma', float, 0.1)
        ctx.params['lr_policy_params'] = {'step_size':iters, 'gamma':gamma}
    elif value == 'SGDR':
        t0 = _prompt('SGDR T-0', int, 50)
        eta  = _prompt('SGDR Min LR', float, 1e-4)
        tmul = _prompt('SGDR T-mult', float, 1)
        #dcay = _prompt('SGDR decay', float, 1)
        ctx.params['lr_policy_params'] = {'T_0':t0, 'eta_min':eta, 'T_mult':tmul}
    elif value == 'CLR':
        raise NotImplementedError

    return value

def model_select(ctx, param, value):
    if value in ['vgg13', 'vgg16', 'resnet34','resnet50']:
        ctx.params['load_imagenet'] = click.confirm("Whether load pretrained ImageNet model?", default=False, abort=False, show_default=True)
        ctx.params['input_nc'] = 3
    else:
        pass

    return value

dataset_list = ['picc_h5', 'all_dr', 'rib']
model_types = ['unet', 'vgg13', 'vgg16', 'resnet34','resnet50','scnn']
losses = ['CE', 'WCE', 'MSE', 'DCE']
lr_schedule = ['const', 'lambda', 'step', 'SGDR', 'plateau']
framework_types = ['segmentation','classification','siamese','selflearning']
layer_orders = ['crb','cbr', 'cgr','cbe','cB']
def common_params(func):
    @click.option('--data-list', prompt=True, type=click.Choice(dataset_list,show_index=True), default=0, help='Data file list (json)')
    @click.option('--framework', prompt=True, type=click.Choice(framework_types,show_index=True), default=1, help='Choose your framework type')
    @click.option('--preload', type=bool, default=True, help='Preload all data once')
    @click.option('--n-epoch', prompt=True, show_default=True, type=int, default=1000, help='Epoch number')
    @click.option('--n-batch', prompt=True, show_default=True, type=int, default=50, help='Batch size')
    @click.option('--istrain', type=bool, default=True, help="train/test phase flag")
    @click.option('--downsample', type=int, default=0, help='Downsample rate. disable:0')
    @click.option('--smooth', type=float, default=0, help='Smooth rate, disable:0')
    @click.option('--input-nc', type=int, default=1, help='input data channels')
    @click.option('--output-nc', type=int, default=3, help='output channels (classes)')
    @click.option('--continue-train', type=bool, default=False, help='continue train mode flag')
    @click.option('--which-epoch', type=int, default=0, callback=partial(prompt_when,trigger='continue_train'), help='used if continue train mode')
    @click.option('--tensor-dim', type=str, default='2D', help='2D or 3D')
    @click.option('--split', type=float, default=0.1, help='Training/testing split ratio')
    @click.option('-W', '--path-pre-trained-model', type=str, default='', help='pretrained model path')
    @click.option('--out-dir', type=str, prompt=True, show_default=True, default='/homes/clwang/Data/picc/exp')
    @click.option('--augment-ratio', type=float, default=0.3, help='Data aug ratio.')
    @click.option('-p', '--partial', type=float, default=1, callback=partial(prompt_when,trigger='debug'), help='Only load part of data')
    @click.option('--save-epoch-freq', type=int, default=20, help='Save model freq')
    @click.option('--seed', type=int, default=101, help='random seed')
    @click.option('--timestamp', type=str, default=time.strftime("%m%d_%H%M"), help='Timestamp')
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

def network_params(func):
    @click.option('--model-type', prompt=True, type=click.Choice(model_types,show_index=True), callback=model_select, default=1, help='Choose model type')
    @click.option('-L', '--criterion', prompt=True, type=click.Choice(losses,show_index=True), default=0, help='loss criterion type')
    @click.option('--crop-size', prompt=True, show_default=True, type=(int,int), default=(72,72), help='Crop volume size')
    @click.option('--n-features', type=int, default=64, help='Feature num of first layer')
    @click.option('--n-level', type=int, default=4, help='Network depth')
    @click.option('--is-deconv', type=bool, default=True, help='use deconv or interplate')
    @click.option('--optim', type=click.Choice(['sgd', 'adam']), default='adam')
    @click.option('--layer-order', prompt=True, type=click.Choice(layer_orders,show_index=True), default=0, help='conv layer order')
    @click.option('-l2', '--l2-reg-weight', type=float, default=0, help='l2 reg weight')
    @click.option('--lr-policy-params', type=dict, default=None, help='Auxilary params for lr schedule')
    @click.option('--lr', type=float, default=1e-3, help='learning rate')
    @click.option('--lr-policy', prompt=True, callback=lr_schedule_params, type=click.Choice(lr_schedule,show_index=True), default=0, help='learning rate strategy')
    @click.option('--feature-scale', type=int, default=4, help='not used')
    @click.option('--snip', is_flag=True)
    @click.option('--snip_percent', type=float, default=0.4, callback=partial(prompt_when,trigger='snip'), help='Pruning ratio of wights/channels')
    # @click.option('--bottleneck', type=bool, default=False, help='Use bottlenect achitecture')
    # @click.option('--sep-conv', type=bool, default=False, help='Use Depthwise Separable Convolution')
    # @click.option('--use-apex', is_flag=True, help='Use NVIDIA apex module')
    # @click.option('--use-half', is_flag=True, help='Use half precision')
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper