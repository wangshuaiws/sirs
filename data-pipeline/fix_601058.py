"""修复 601058 的 adj 数据"""
from calc_indicators_rest import batch_read_raw, compute_one, write_one_stock
raw = batch_read_raw(['601058'])
code, name, adj, args = compute_one('601058', '', raw['601058'])
if write_one_stock(code, name, adj, args):
    print(f'601058 修复完成, {len(adj)} bars')
else:
    print('失败')
