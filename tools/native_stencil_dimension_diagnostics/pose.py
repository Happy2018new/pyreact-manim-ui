"""Host-side bounded room requests; SDK work is in memory and never writes files."""
import math


STATE = '_pmanim_stencil_positive_pose_v3'
CAMERA = (8., 72., 5.)
PLAYER_FEET = (8.5, 70., 8.5)
DIMENSION_TARGET = (8, 72, 8)
# All blocks lie inside chunk (0,0), avoiding the failed run's zero boundary.
MINIMUM = (4, 69, 3)
MAXIMUM = (12, 78, 13)
ROOM_BLOCKS = 9*10*11
MAX_WRITE_ATTEMPTS = 3


def vector(value):
    return (isinstance(value, (list, tuple)) and len(value) == 3 and
            all(isinstance(item, (int, float)) and not isinstance(item, bool) and
                math.isfinite(item) for item in value))


def legal_pose(camera, anchor):
    return (vector(camera) and vector(anchor) and
            all(abs(camera[i]-CAMERA[i]) <= .01 for i in range(3)) and
            all(70. <= point[1] <= 77. and 4.5 <= point[0] <= 11.5 and
                3.5 <= point[2] <= 12.5 for point in (camera, anchor)))


def room_request(dimensions=(0, 1)):
    """Install serial callback-guarded writes and later fresh-callback verification.

    Only dimension 0's initial write is dispatched here. Later SDK requests come
    from separate delayed host commands. Mismatches alone may be rewritten, with
    at most three write attempts. Originals are copied once before first writes.
    """
    dimensions = tuple(dimensions)
    if dimensions not in ((0,), (0, 1)):
        raise ValueError('Choose the Overworld foothold or both controlled rooms')
    return """factory=api.GetEngineCompFactory()
level=api.GetLevelId()
if hasattr(api,%r): raise RuntimeError('Positive pose rooms already requested')
state={'schema':'positive_pose_rooms_v3','dimensions':%r,'rooms':{},'backups':[],'backup_index':{},
       'last_writes':{},'restored':False,'cancelled':False,'epoch':0,'mode':'prepare'}
setattr(api,%r,state)
blocks=factory.CreateBlockInfo(level)
chunks=factory.CreateChunkSource(level)
positions=[(x,y,z) for x in range(4,13) for y in range(69,79) for z in range(3,14)]
corners=[(x,72,z) for x in (4,12) for z in (3,13)]
def new_row():
    return {'phase':'queued','verified_blocks':0,'error':None,'attempts':0,
            'request_serial':0,'write_calls':0,'mismatch_count':0,
            'first_mismatches':[],'retry_positions':[],'chunk_checks':[],
            'verification_history':[]}
for dimension in state['dimensions']: state['rooms'][str(dimension)]=new_row()
def desired(position):
    x,y,z=position
    shell=(x in (4,12) or y in (69,78) or z in (3,13))
    return {'name':'minecraft:stone' if shell else 'minecraft:air','aux':0}
def same(actual,wanted):
    return actual is not None and actual.get('name')==wanted.get('name') and actual.get('aux',0)==wanted.get('aux',0)
def advance(state=state,blocks=blocks,chunks=chunks,positions=positions,corners=corners,
            desired=desired,same=same):
    mode=state['mode']
    rows=state['rooms'] if mode=='prepare' else state['restore_rooms']
    if mode=='prepare' and state['cancelled']: return {'dispatched':False,'cancelled':True}
    if any(row['phase'] in ('loading','working') for row in rows.values()):
        return {'dispatched':False,'pending':True}
    dimension=next((item for item in state['dimensions'] if rows[str(item)]['phase'] not in ('ready','failed')),None)
    if dimension is None: return {'dispatched':False,'complete':True}
    row=rows[str(dimension)]
    stage='verify' if row['phase']=='await_verify' else 'write'
    row['request_serial']+=1
    serial=row['request_serial']
    epoch=state['epoch']
    row.update(phase='loading',stage=stage)
    def callback(data,dimension=dimension,mode=mode,stage=stage,serial=serial,epoch=epoch,
                 state=state,row=row,rows=rows,blocks=blocks,chunks=chunks,positions=positions,
                 corners=corners,desired=desired,same=same):
        if (state['epoch']!=epoch or state['mode']!=mode or row['request_serial']!=serial or
                row['phase']!='loading' or (mode=='prepare' and state['cancelled'])):
            return
        if data.get('code',0)!=1:
            row.update(phase='failed',error='Async chunk load rejected')
            return
        row['chunk_checks']=[{'position':point,'loaded':chunks.CheckChunkState(dimension,point)} for point in corners]
        if state['epoch']!=epoch or state['mode']!=mode or (mode=='prepare' and state['cancelled']): return
        if not all(check['loaded'] is True for check in row['chunk_checks']):
            row.update(phase='failed',error='Room corner chunk state rejected')
            return
        row['phase']='working'
        try:
            selected=positions if mode=='prepare' else [tuple(item['position']) for item in state['backups'] if item['dimension']==dimension]
            if stage=='write':
                row['attempts']+=1
                targets=row['retry_positions'] if row['retry_positions'] else selected
                for position in targets:
                    if state['epoch']!=epoch or state['mode']!=mode or (mode=='prepare' and state['cancelled']): return
                    position=tuple(position)
                    key=(dimension,position)
                    before=blocks.GetBlockNew(position,dimension)
                    if state['epoch']!=epoch or state['mode']!=mode or (mode=='prepare' and state['cancelled']): return
                    if before is None:
                        row['first_mismatches']=[{'position':position,'actual':None,'stage':'before_write'}]
                        raise RuntimeError('Loaded room block unavailable')
                    before=dict(before)
                    if mode=='prepare' and key not in state['backup_index']:
                        backup={'dimension':dimension,'position':position,'block':dict(before)}
                        state['backup_index'][key]=backup
                        state['backups'].append(backup)
                    wanted=dict(desired(position) if mode=='prepare' else state['backup_index'][key]['block'])
                    accepted=blocks.SetBlockNew(position,wanted,0,dimension,mode=='prepare',False)
                    state['last_writes'][key]={'accepted':accepted,'before':dict(before),'wanted':dict(wanted),'attempt':row['attempts']}
                    row['write_calls']+=1
                    if state['epoch']!=epoch or state['mode']!=mode or (mode=='prepare' and state['cancelled']): return
                row['phase']='await_verify'
            else:
                mismatches=[]
                for position in selected:
                    if state['epoch']!=epoch or state['mode']!=mode or (mode=='prepare' and state['cancelled']): return
                    key=(dimension,tuple(position))
                    wanted=desired(position) if mode=='prepare' else state['backup_index'][key]['block']
                    actual=blocks.GetBlockNew(tuple(position),dimension)
                    if not same(actual,wanted):
                        mismatches.append({'position':position,'wanted':dict(wanted),'actual':dict(actual) if actual is not None else None,
                            'original':state['backup_index'][key]['block'],
                            'last_write':state['last_writes'].get(key)})
                if state['epoch']!=epoch or state['mode']!=mode or (mode=='prepare' and state['cancelled']): return
                row['verified_blocks']=len(selected)-len(mismatches)
                row['mismatch_count']=len(mismatches)
                row['first_mismatches']=mismatches[:16]
                row['retry_positions']=[item['position'] for item in mismatches]
                row['verification_history'].append({'attempt':row['attempts'],
                    'mismatch_count':len(mismatches),'first_mismatches':mismatches[:16]})
                if mismatches:
                    row['phase']='await_retry' if row['attempts']<3 else 'failed'
                    row['error']=None if row['attempts']<3 else 'Room verification mismatch after bounded retries'
                else:
                    row.update(phase='ready',error=None)
            if mode=='restore':
                state['restored']=len(rows)==len(state['dimensions']) and all(item['phase']=='ready' for item in rows.values())
        except (RuntimeError,ValueError,TypeError,KeyError) as error:
            row.update(phase='failed',error=str(error))
    accepted=chunks.DoTaskOnChunkAsync(dimension,(4,69,3),(12,78,13),callback)
    if accepted is not True and row['phase']=='loading':
        row.update(phase='failed',error='Chunk request rejected')
    return {'dispatched':True,'dimension':dimension,'stage':stage,'serial':serial,'accepted':accepted}
state['advance']=advance
state['new_row']=new_row
requested=advance()
_result=json.dumps({'requests':[requested],'rooms':state['rooms']})
""" % (STATE, dimensions, STATE)


def room_advance():
    return "state=getattr(api,%r)\n_result=json.dumps(state['advance']())" % STATE


def room_status(include_backups=False):
    return ("state=getattr(api,%r)\n" % STATE+
            "_result=json.dumps({'rooms':state['rooms'],'backup_count':len(state['backups']),"
            "'restored':state['restored'],'cancelled':state['cancelled']"+
            (",'backups':state['backups']" if include_backups else '')+"})")


def restore_rooms():
    return """state=getattr(api,%r,None)
if state is None:
    _result=json.dumps({'requested':False,'all_exact':True,'count':0})
else:
    if state.get('restore_rooms'): raise RuntimeError('Room restoration already requested')
    state['cancelled']=True
    state['epoch']+=1
    state['mode']='restore'
    state['restore_rooms']={str(dimension):state['new_row']() for dimension in state['dimensions']}
    requested=state['advance']()
    _result=json.dumps({'requested':True,'requests':[requested]})
""" % STATE


def restore_status():
    return ("state=getattr(api,%r,None)\n" % STATE+
            "_result=json.dumps({'requested':state is not None,'all_exact':state is None or state['restored'],"
            "'count':len(state['backups']) if state is not None else 0,"
            "'rooms':state.get('restore_rooms',{}) if state is not None else {}})")
