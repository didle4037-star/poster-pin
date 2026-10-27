bl_info = {'name':'Print & Pin · Poster Pin','author':'G_ni','version': (1, 41, 0),'blender':(5,2,0),
           'location':'3D View > Sidebar > Poster Pin','description':'Print & Pin, part 2: pin posters onto walls and strings in layers, with tape, pins and clips','category':'Object'}
import bpy, bmesh, math, random, bisect, hashlib, time
import numpy as np
from mathutils import Vector, Matrix, Euler
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform
from bpy.props import PointerProperty, IntProperty, FloatProperty, BoolProperty, StringProperty, EnumProperty, CollectionProperty
import os, json, sys

# ---------------------------------------------------------------- Language (English / 한국어)
# The UI language is an add-on preference (default English), shared by Poster Print and Poster Pin in
# <Blender config>/print_pin_language.json. Panel, editor and message text switch right away; labels and
# tooltips that Blender stores at registration (operator names, property names) follow after a restart.
import re as _i18n_re
_I18N={'lang':None,'cache':{},'tpl':None}
def _i18n_file():
    try:return os.path.join(bpy.utils.user_resource('CONFIG'),'print_pin_language.json')
    except Exception:return ''
def _i18n_lang():
    if _I18N['lang'] is None:
        lang='EN'
        try:
            with open(_i18n_file(),encoding='utf-8') as f:lang=json.load(f).get('lang','EN')
        except Exception:pass
        _I18N['lang']=lang if lang in ('EN','KO') else 'EN'
    return _I18N['lang']
def _i18n_set(lang):
    _I18N['lang']=lang;_I18N['cache'].clear()
    try:
        p=_i18n_file();os.makedirs(os.path.dirname(p),exist_ok=True)
        with open(p,'w',encoding='utf-8') as f:json.dump({'lang':lang},f)
    except Exception:pass
    for mod in ('poster_atlas','poster_scatter'):   # the other add-on reads the same file: reset its copy too
        m=sys.modules.get(mod)
        if m is not None and getattr(m,'_I18N',None) is not None and m._I18N is not _I18N:
            m._I18N['lang']=lang;m._I18N['cache'].clear()
    try:
        for w in bpy.context.window_manager.windows:
            for a in w.screen.areas:a.tag_redraw()
    except Exception:pass
_I18N_SPEC=_i18n_re.compile(r'%%|%[-+ 0#]*\d*(?:\.\d+)?[diouxXeEfFgGs]')
def _i18n_templates():
    if _I18N['tpl'] is None:
        tpl=[]
        for en,ko in _KO.items():
            if '%' not in en or not _I18N_SPEC.search(en.replace('%%','')):continue
            parts=[];pos=0
            for m in _I18N_SPEC.finditer(en):
                parts.append(_i18n_re.escape(en[pos:m.start()]));t=m.group()
                if t=='%%':parts.append('%')
                elif t[-1] in 'dioux':parts.append(r'(-?\d+)')
                elif t[-1] in 'X':
                    w=_i18n_re.search(r'(\d+)X$',t);parts.append(r'([0-9A-Fa-f]{%s})'%w.group(1) if w else r'([0-9A-Fa-f]+)')
                elif t[-1]=='s':parts.append(r'(.*?)')
                else:parts.append(r'(-?[0-9.eE+\-]+|inf|nan)')
                pos=m.end()
            parts.append(_i18n_re.escape(en[pos:]))
            try:tpl.append((len(en),_i18n_re.compile(''.join(parts)+r'\Z',_i18n_re.S),ko,en in _I18N_TR_ARGS))
            except _i18n_re.error:pass
        tpl.sort(key=lambda t:-t[0]);_I18N['tpl']=tpl
    return _I18N['tpl']
_I18N_SEPS=('  ·  ','  |  ',' · ',' | ')
_I18N_TR_ARGS={'Eyedropper (%s): click a poster or a color cell · Esc = Cancel','%s set with eyedropper · #%02X%02X%02X',
    '%s on %d image(s)','Look: %s · %d image(s)','Surface: %s · %d image(s)','Turned off %s','Applied %s','Removed %s.',
    'Cleared %s effects','%s has no effects to clear','Previewing: %s · %d posters','%d selected: applied [%s] · pick another effect to stack on top.',
    'Paint · %s — drag over a poster  |  [ ] brush size  |  right-click to stop','Scale %s with mouse','Changed to %s · poster sizes kept%s · Ctrl+Z to undo',
    '%s ×%d','Surface · %s','%s %d','%s  ·  %d','Added %d image(s) to the %s list','Size %d%%  ·  move left / right  ·  Ctrl 5%% steps  ·  R rotate  ·  %s  ·  Esc cancel',
    'Rotate %.0f°  ·  Ctrl 15° steps  ·  S size  ·  %s  ·  Esc cancel','Move  ·  keep holding and press S size / R rotate  ·  %s',
    '%s  [angle %.0f° · scale %d%%%s]  %s','Layer %d: placed %d poster%s %s','Layer %d · %s','%s|%d','%s  %d×%d',
    'Make %d-Cut  ·  %s card  (%d selected)','Photo strip %d×%d on a %s card (%.0f×%.0f mm) from %d photo(s)%s · originals unchecked in the list',
    'Too many cells for a %s card.','%d images · one %s sheet (~%d A4)','Not all current posters fit on the %s canvas · remove a few or reduce their size.',
    'Auto %d · Manual %d%s%s · %.2fs','Packed %d selected into the free space · others stay put%s · Ctrl+Z to undo','Green inset %d px%s',
    'Photo strip %d×%d','%d × %d px  |  Rotation %d°  |  %s','Applied to %d selected: %s','= %d posters%s','Paper Crumple · %s','Custom (pattern %d)'}
def _i18n_tr(s,depth=0):
    k=_KO.get(s)
    if k is not None:return k
    st=s.strip()
    if st!=s and st:
        k=_i18n_tr(st,depth+1)
        if k!=st:return s[:len(s)-len(s.lstrip())]+k+s[len(s.rstrip()):]
        return s
    for _,rx,ko,tr_args in _i18n_templates():
        m=rx.match(s)
        if m:
            g=m.groups()
            # values are names of the user's data (collections, objects) unless the message only ever gets UI words
            return _i18n_re.sub(r'\{(\d+)\}',lambda mm:(_i18n_tr(g[int(mm.group(1))],depth+1) if tr_args else g[int(mm.group(1))]) if int(mm.group(1))<len(g) else '',ko)
    if depth<4:
        for sep in _I18N_SEPS:
            if sep in s:
                parts=s.split(sep);out=[_i18n_tr(p,depth+1) for p in parts]
                if out!=parts:return sep.join(out)
    return s
def _T(s):
    """English UI text -> current language (English when the preference is English)."""
    if not isinstance(s,str) or not s or _i18n_lang()!='KO':return s
    c=_I18N['cache'];r=c.get(s)
    if r is None:
        try:r=_i18n_tr(s)
        except Exception:r=s
        if len(c)>20000:c.clear()
        c[s]=r
    return r
_I18N_KEEP={}
def _T_items(items):
    """Translate the name / description of EnumProperty items (identifiers stay English)."""
    if callable(items):
        fn=items
        def cb(self,context):
            res=fn(self,context)
            if _i18n_lang()!='KO' or not res:return res
            out=[tuple((_T(v) if i in (1,2) and isinstance(v,str) else v) for i,v in enumerate(it)) if isinstance(it,tuple) and len(it)>=3 else it for it in res]
            _I18N_KEEP[id(fn)]=out   # Blender needs the strings kept alive
            return out
        return cb
    try:return [tuple((_T(v) if i in (1,2) and isinstance(v,str) else v) for i,v in enumerate(it)) if isinstance(it,(tuple,list)) and len(it)>=3 else it for it in items]
    except TypeError:return items
def _i18n_lang_changed(self,context):_i18n_set(self.language)

# Korean UI text (English key -> Korean). {0},{1}.. = values in order.
_KO={' (excluded %d all-green cells)': ' (전부 초록인 칸 {0}개 제외)',
 ' (left smaller / right bigger)': ' (왼쪽 작게 / 오른쪽 크게)',
 ' (no posters placed?)': ' (붙은 포스터가 없나요?)',
 ' (toward / away from center)': ' (중심 쪽 / 바깥쪽)',
 ' : a flat poster in the local XY plane is required.': ' : 로컬 XY 평면에 놓인 평평한 포스터가 필요해요.',
 ' : empty mesh.': ' : 빈 메시예요.',
 ' | Inside: move photo / Border: crop / Shift wheel: zoom photo': ' | 안쪽: 사진 이동 / 테두리: 자르기 / Shift 휠: 사진 확대',
 ' | Keep whole photo ratio': ' | 사진 전체 비율 유지',
 ' | Layout-only rotation %d°': ' | 레이아웃에서만 회전 {0}°',
 ' | Width·height independent': ' | 가로·세로 따로',
 ' · %d groups': ' · 그룹 {0}개',
 ' · %d lack free space: please adjust the overlap.': ' · {0}개는 빈 공간이 부족해요: 겹침을 조정해 주세요.',
 ' · %d not used': ' · {0}장은 쓰지 않았어요',
 ' · %d photo card%s now custom size': ' · 사진 카드 {0}장이 직접 입력 크기로 바뀌었어요',
 ' · %d photo(s) reused to fill %d cells': ' · 칸 {1}개를 채우려고 사진 {0}장을 다시 썼어요',
 ' · %d removed from the list': ' · 목록에서 {0}장 뺌',
 ' · %d skipped (already in the list or not an image)': ' · {0}장 건너뜀 (이미 목록에 있거나 이미지가 아님)',
 ' · %d turned 90° in the texture only': ' · {0}장은 텍스처 안에서만 90° 돌렸어요',
 ' · %d without a photo card skipped': ' · 사진 카드가 아닌 {0}장은 건너뜀',
 ' · Attached %d': ' · 부착 {0}개',
 ' · Ctrl+Z to undo': ' · Ctrl+Z로 되돌리기',
 ' · Shift fine · Ctrl 5% steps · Click/S/Enter confirm · Esc revert': ' · Shift 세밀 · Ctrl 5% 단위 · 클릭/S/Enter 확정 · Esc 되돌리기',
 ' · W %d%% · H %d%%': ' · 가로 {0}% · 세로 {1}%',
 ' · X width / Y or Z height': ' · X 가로 / Y나 Z 세로',
 ' · green becomes transparent when saving · Ctrl+Z to undo': ' · 저장할 때 초록은 투명해져요 · Ctrl+Z로 되돌리기',
 ' · it now overlaps other images: press Pack': ' · 다른 이미지와 겹쳐요: Pack을 누르세요',
 ' · others kept': ' · 나머지는 그대로',
 ' · re-packed to fit': ' · 맞게 다시 배치함',
 ' · repeat limit reached': ' · 반복 한도 도달',
 ' · replaced %d pieces from an earlier cut of this sheet (Ctrl+Z brings them back)': ' · 이 시트를 예전에 자른 조각 {0}개를 바꿨어요 (Ctrl+Z로 되돌릴 수 있어요)',
 ' · sheet taken off the cut list': ' · 원본 시트는 자르기 목록에서 뺐어요',
 ' · updated %d placed posters': ' · 벽에 붙인 포스터 {0}장 업데이트',
 ' · used by Trim Green / Find Cells': " · '초록 잘라 맞추기 / 칸 찾기'에 쓰여요",
 ' × reuse': ' × 반복',
 '" / " starts a new line · empty text removes the caption': '" / "로 줄바꿈 · 비우면 문구가 지워져요',
 '" / " starts a second line. Latin letters only: the handwriting fonts have no Korean': '" / "로 두 번째 줄을 시작해요. 영문만 돼요: 손글씨 글꼴에 한글이 없어요',
 '"%s" added at the 3D cursor': '"{0}"를 3D 커서 위치에 추가했어요',
 '"%s" has %d edges, too many for a rail. Use a thin curve or line, or in Edit Mode select only the edges to hang from.': '"{0}"는 변이 {1}개라 레일로 쓰기엔 너무 많아요. 얇은 '
                                                                                                                          '커브나 선을 쓰거나, 편집 모드에서 걸 변만 선택하세요.',
 '"%s" is too detailed for a rail (%d segments even after simplifying). Use a simpler curve.': '"{0}"는 레일로 쓰기엔 너무 촘촘해요 (단순화해도 {1}구간). 더 단순한 커브를 쓰세요.',
 '"%s" splits into %d separate pieces, which looks like a surface rather than a line. Use a thin curve, or select only the hanging edges in Edit Mode.': '"{0}"는 '
                                                                                                                                                         '{1}조각으로 '
                                                                                                                                                         '나뉘어 '
                                                                                                                                                         '선이 '
                                                                                                                                                         '아니라 '
                                                                                                                                                         '면처럼 '
                                                                                                                                                         '보여요. '
                                                                                                                                                         '얇은 '
                                                                                                                                                         '커브를 '
                                                                                                                                                         '쓰거나, '
                                                                                                                                                         '편집 '
                                                                                                                                                         '모드에서 '
                                                                                                                                                         '걸 변만 '
                                                                                                                                                         '선택하세요.',
 '%d col': '{0}열',
 '%d group%s': '그룹 {0}개',
 '%d groups are in use · No Group on their posters first': "그룹 {0}개가 쓰이고 있어요 · 먼저 그 포스터들을 '그룹 없음'으로",
 '%d image%s outside the texture (red frame: %s) · move them back in or press Pack, then Build': '이미지 {0}장이 텍스처 밖에 있어요 (빨간 틀: {2}) · 안으로 옮기거나 Pack을 누른 뒤 만들기',
 '%d image%s → %s': '이미지 {0}장 → {2}',
 '%d images': '이미지 {0}장',
 '%d images to cut': '자를 이미지 {0}장',
 '%d images · one %s sheet (~%d A4)': '이미지 {0}장 · {1} 시트 한 장 (A4 약 {2}장)',
 '%d marked edges': '표시한 변 {0}개',
 '%d pinned · auto posters move around them': '{0}장 고정 · 자동 포스터가 그 주변으로 움직여요',
 '%d poster object%s inside': '포스터 오브젝트 {0}개 들어 있음',
 '%d poster%s ready': '포스터 {0}장 준비됨',
 '%d random colors': '랜덤 색 {0}개',
 '%d row': '{0}행',
 '%d selected · ': '{0}장 선택 ·',
 '%d selected: applied [%s] · pick another effect to stack on top.': '선택한 {0}장: [{1}] 적용 · 다른 효과를 골라 위에 겹칠 수 있어요.',
 '%d variants': '변형 {0}개',
 '%d × %d px  |  Rotation %d°  |  %s': '{0} × {1} px  |  회전 {2}°  |  {3}',
 '%d × %d px texture': '{0} × {1} px 텍스처',
 '%d. %s': '{0}. {1}',
 '%s  %d×%d': '{0}  {1}×{2}',
 '%s  [angle %.0f° · scale %d%%%s]  %s': '{0}  [각도 {1}° · 크기 {2}%{3}]  {4}',
 '%s %d': '{0} {1}',
 '%s color %s: %d meshes': '{0} 색 {1}: 메시 {2}개',
 '%s has no effects to clear': '{0}에는 지울 효과가 없어요',
 '%s on %d image(s)': '이미지 {1}장에 {0}',
 '%s set with eyedropper · #%02X%02X%02X': '스포이트로 {0} 지정 · #{1}{2}{3}',
 '%s · %d': '{0} · {1}',
 '%s · %d  →  %s': '{0} · {1}  →  {2}',
 '%s · Layer %d': '{0} · 레이어 {1}',
 '%s ×%d': '{0} ×{1}',
 '(none)': '(없음)',
 '+ Add': '+ 추가',
 '0 = smallest · 1 = largest': '0 = 가장 작음 · 1 = 가장 큼',
 '0 uses all cells of the last image. Row-major from the top.': '0이면 마지막 이미지의 모든 칸을 써요. 위에서부터 행 순서.',
 '1 bends evenly from the tape; higher bends mostly at the ends': '1이면 테이프에서부터 고르게 휘고, 높을수록 끝에서 주로 휘어요',
 '1. Pick your poster collection': '1. 포스터 컬렉션 고르기',
 '2. Select where they go': '2. 붙일 곳 선택',
 '2048 × 2048 px texture': '2048 × 2048 px 텍스처',
 '3. Press the button': '3. 버튼 누르기',
 '4 or more bends smoothly': '4 이상이면 부드럽게 휘어요',
 '4096 × 4096 px texture': '4096 × 4096 px 텍스처',
 '= %d posters%s': '= 포스터 {0}장{1}',
 'A bottom-left or bottom-right corner curls up diagonally': '왼쪽 아래 또는 오른쪽 아래 모서리가 대각선으로 말려요',
 'A collection with your tapes or objects. Model each lying flat (XY), +Z away from the wall, origin where it touches the paper. One is picked at random per spot': '테이프나 '
                                                                                                                                                                    '오브젝트가 '
                                                                                                                                                                    '든 '
                                                                                                                                                                    '컬렉션. '
                                                                                                                                                                    '각각 '
                                                                                                                                                                    '평평하게(XY), '
                                                                                                                                                                    '+Z가 '
                                                                                                                                                                    '벽 '
                                                                                                                                                                    '바깥, '
                                                                                                                                                                    '원점은 '
                                                                                                                                                                    '종이에 '
                                                                                                                                                                    '닿는 '
                                                                                                                                                                    '곳으로 '
                                                                                                                                                                    '모델링하세요. '
                                                                                                                                                                    '자리마다 '
                                                                                                                                                                    '하나씩 '
                                                                                                                                                                    '랜덤으로 '
                                                                                                                                                                    '골라요',
 'A curve, or a mesh whose edges (selected ones, if marked) form the rail. Papers hang from it': '커브, 또는 변(표시했다면 선택한 변)이 레일이 되는 메시. 종이가 여기에 걸려요',
 'A different pattern (seed) of the same texture.': '같은 질감의 다른 무늬(시드)예요.',
 'A paper rises only where it actually lies over a paper below and ramps over its edge, instead of the whole paper being raised. Stacks no longer float. Off: the older whole-paper raise': '종이 '
                                                                                                                                                                                            '전체를 '
                                                                                                                                                                                            '띄우지 '
                                                                                                                                                                                            '않고, '
                                                                                                                                                                                            '아래 '
                                                                                                                                                                                            '종이 '
                                                                                                                                                                                            '위에 '
                                                                                                                                                                                            '실제로 '
                                                                                                                                                                                            '겹친 '
                                                                                                                                                                                            '부분만 '
                                                                                                                                                                                            '올라가며 '
                                                                                                                                                                                            '가장자리를 '
                                                                                                                                                                                            '넘어가요. '
                                                                                                                                                                                            '쌓인 '
                                                                                                                                                                                            '종이가 '
                                                                                                                                                                                            '뜨지 '
                                                                                                                                                                                            '않아요. '
                                                                                                                                                                                            '끄면 '
                                                                                                                                                                                            '예전처럼 '
                                                                                                                                                                                            '종이 '
                                                                                                                                                                                            '전체를 '
                                                                                                                                                                                            '올려요',
 'A wall, floor, curve or edges': '벽, 바닥, 커브 또는 변',
 'Across': '가로',
 'Across the corners, diagonally (like taped-up posters)': '모서리에 대각선으로 (테이프로 붙인 포스터처럼)',
 'Actually eats into the paper border so the silhouette becomes ragged.': '실제로 종이 테두리를 파고들어서 실루엣이 울퉁불퉁해져요.',
 'Add': '추가',
 'Add Clothespin': '빨래집게 추가',
 'Add Color': '색 추가',
 'Add Dropped Images': '놓은 이미지 추가',
 'Add Images': '이미지 추가',
 'Add Images to Cut': '자를 이미지 추가',
 'Add Layer': '레이어 추가',
 'Add Layer = more posters in the gaps': '레이어 추가 = 빈 곳에 포스터 더',
 'Add Range': '구간 추가',
 'Add Text  (T)': '글자 추가  (T)',
 'Add another scatter on the same wall, on top of this stack. It fills the empty space around the posters below (or lies over them, see With Posters Below). Press again for more layers': '같은 '
                                                                                                                                                                                           '벽에 '
                                                                                                                                                                                           '이 '
                                                                                                                                                                                           '스택 '
                                                                                                                                                                                           '위로 '
                                                                                                                                                                                           '스캐터를 '
                                                                                                                                                                                           '하나 '
                                                                                                                                                                                           '더 '
                                                                                                                                                                                           '만들어요. '
                                                                                                                                                                                           '아래 '
                                                                                                                                                                                           '포스터 '
                                                                                                                                                                                           '주변 '
                                                                                                                                                                                           '빈 '
                                                                                                                                                                                           '곳을 '
                                                                                                                                                                                           '채우거나(또는 '
                                                                                                                                                                                           '그 '
                                                                                                                                                                                           '위에 '
                                                                                                                                                                                           '얹거나, '
                                                                                                                                                                                           "'아래 "
                                                                                                                                                                                           '포스터와의 '
                                                                                                                                                                                           "관계' "
                                                                                                                                                                                           '참고) '
                                                                                                                                                                                           '해요. '
                                                                                                                                                                                           '더 '
                                                                                                                                                                                           '누르면 '
                                                                                                                                                                                           '레이어가 '
                                                                                                                                                                                           '늘어요',
 'Added %d image(s) to the %s list': '{1} 목록에 이미지 {0}장 추가',
 'Adjusts width and height independently. The photo ratio may change.': '가로·세로를 따로 조절해요. 사진 비율이 바뀔 수 있어요.',
 'After a successful Build, the images that went into it leave the image list, so only the ones still to do remain. Image files on disk are kept; Re-edit brings a batch back': '만들기가 '
                                                                                                                                                                                '끝나면 '
                                                                                                                                                                                '거기 '
                                                                                                                                                                                '쓰인 '
                                                                                                                                                                                '이미지는 '
                                                                                                                                                                                '목록에서 '
                                                                                                                                                                                '빠져서 '
                                                                                                                                                                                '남은 '
                                                                                                                                                                                '것만 '
                                                                                                                                                                                '보여요. '
                                                                                                                                                                                '디스크의 '
                                                                                                                                                                                '이미지 '
                                                                                                                                                                                '파일은 '
                                                                                                                                                                                '그대로고, '
                                                                                                                                                                                '다시 '
                                                                                                                                                                                '편집하면 '
                                                                                                                                                                                '배치가 '
                                                                                                                                                                                '돌아와요',
 'After choosing, press [Apply to Selection].': '고른 뒤 [선택에 적용]을 누르세요.',
 'Aged Edges': '낡은 가장자리',
 'All': '전체',
 'All Fonts…': '모든 글꼴…',
 'All Four': '네 곳 모두',
 'All Off': '모두 끄기',
 'All Posters': '모든 포스터',
 'All dark parts in the same color': '어두운 부분 전부 같은 색으로',
 'All effects off on %d poster%s · Ctrl+Z to undo': '포스터 {0}장 효과 모두 끔 · Ctrl+Z로 되돌리기',
 'All faces of ': '모든 면:',
 'All faces of %s': '{0}의 모든 면',
 'All posters on the same paper color': '모든 포스터를 같은 종이 색으로',
 'Allow Overlap': '겹침 허용',
 'Along Rail': '레일 따라',
 'Already numbered in that order.': '이미 그 순서로 번호가 매겨져 있어요.',
 'Already the original color': '이미 원래 색이에요',
 'Also scale with the poster (Scale and Random Scale)': '포스터와 함께 크기도 바뀌어요 (크기와 랜덤 크기)',
 'Amount of holes torn out of the middle of the paper. At 1, up to about half the area is punched.': '종이 가운데에 찢겨 난 구멍의 양이에요. 1이면 면적의 절반 정도까지 뚫려요.',
 'Angle': '각도',
 'Applied %s': '{0} 적용함',
 'Applied paint to %d images.': '이미지 {0}장에 칠하기를 적용했어요.',
 'Applied to %d selected · loaded values of #%d': '선택한 {0}장에 적용 · #{1} 값을 불러옴',
 'Applied to %d selected: %s': '선택한 {0}개에 적용: {1}',
 'Applies paint and setting changes about every 0.4 seconds. Many posters take longer to compute.': '칠하기와 설정 변경을 약 0.4초마다 적용해요. 포스터가 많으면 계산이 오래 걸려요.',
 'Apply  ·  Save PNG': '적용  ·  PNG 저장',
 'Apply Crop': '자르기 적용',
 'Apply Paper Texture': '종이 질감 적용',
 'Apply to All Posters': '모든 포스터에 적용',
 'Apply · Build Posters': '적용 · 포스터 만들기',
 'Area Range End': '면적 구간 끝',
 'Areas': '영역',
 'Arrange': '배치',
 'At least one color is required.': '색은 하나 이상 있어야 해요.',
 'Attach Mode': '붙이는 방식',
 'Attachments: ': '부착물:',
 'Attachments: %s': '부착물: {0}',
 'Auto %d · Manual %d%s%s · %.2fs': '자동 {0} · 수동 {1}{2}{3} · {4}초',
 'Auto · fit image count': '자동 · 이미지 수에 맞춤',
 'Auto-apply on Build': '만들 때 자동 적용',
 'B&W': '흑백',
 'Back to default settings (rotation, lift, overlap and reuse off, count linked). Collection, painting, pinned posters and the rail are kept': '기본 설정으로 되돌려요 '
                                                                                                                                               '(회전, 들뜸, 겹침, '
                                                                                                                                               '반복 끔, 개수 연결). '
                                                                                                                                               '컬렉션, 칠하기, 고정한 '
                                                                                                                                               '포스터, 레일은 그대로예요',
 'Background': '배경',
 'Bake New Texture in Substance': 'Substance로 새 질감 굽기',
 'Bake Resolution': '굽기 해상도',
 'Bake failed: ': '굽기 실패:',
 'Bake failed: %s': '굽기 실패: {0}',
 'Bake from Substance File': 'Substance 파일로 굽기',
 'Baked %s, %d variants.': '{0}을(를) 변형 {1}개로 구웠어요.',
 'Baked torn-edge %s, %d variants. Re-apply to use them on worn edges.': '찢긴 가장자리 {0}을(를) 변형 {1}개로 구웠어요. 다시 적용하면 닳은 가장자리에 쓰여요.',
 'Bakes a .sbs or .sbsar into tiling textures with the Substance Designer command-line tools and adds them to the paper texture folder.': '.sbs 또는 .sbsar를 '
                                                                                                                                          'Substance Designer '
                                                                                                                                          '명령줄 도구로 반복 질감으로 구워 '
                                                                                                                                          '종이 질감 폴더에 넣어요.',
 'Ballpoint·Marker': '볼펜·마커',
 'Batch %d': '배치 {0}',
 'Batch Name': '배치 이름',
 'Batch name': '배치 이름',
 'Bend Curve': '휨 곡선',
 'Bend Width': '휨 폭',
 'Bends by curl angle instead of height. Above 90° the end rolls up into a curl.': '높이 대신 말림 각도로 휘어요. 90°를 넘으면 끝이 동그랗게 말려요.',
 'Big ones first, small ones fill gaps': '큰 것 먼저, 작은 것은 틈에',
 'Black': '검정',
 'Black Marker': '검정 마커',
 'Black background': '검은 배경',
 'Blue': '파랑',
 'Blue Pen': '파란 펜',
 'Bold': '굵게',
 'Bold Sans': '굵은 고딕',
 'Border Roughness': '테두리 거칠기',
 'Borderless': '테두리 없음',
 'Both': '둘 다',
 'Both bottom corners together': '아래 두 모서리 함께',
 'Both top corners': '위 두 모서리',
 'Bottom': '아래',
 'Bottom (mm)': '아래 (mm)',
 'Bottom corners': '아래 모서리',
 'Bottom edge': '아래 가장자리',
 'Bottom, side and corner edges of paper stuck to the wall lift up': '벽에 붙인 종이의 아래·옆·모서리 가장자리가 들려요',
 'Boundary with the next range. Smallest area is 0, largest is 1.': '다음 구간과의 경계. 가장 작은 면적이 0, 가장 큰 면적이 1이에요.',
 'Box-select multiple images': '여러 이미지를 상자로 선택',
 'Brick Offset': '벽돌식 어긋남',
 'Brush Size mm': '브러시 크기 mm',
 'Brush Strength': '브러시 강도',
 'Brush Tip': '브러시 끝',
 'Build  ·  Texture + Posters': '만들기  ·  텍스처 + 포스터',
 'Build puts each group in its own collection inside the batch (e.g. Photos for the string, Notes for the wall), so Scatter can use them separately. Empty: stays in the batch itself': '만들기를 '
                                                                                                                                                                                        '하면 '
                                                                                                                                                                                        '그룹마다 '
                                                                                                                                                                                        '배치 '
                                                                                                                                                                                        '안에 '
                                                                                                                                                                                        '자기 '
                                                                                                                                                                                        '컬렉션이 '
                                                                                                                                                                                        '생겨서(예: '
                                                                                                                                                                                        '끈에 '
                                                                                                                                                                                        '걸 '
                                                                                                                                                                                        '사진, '
                                                                                                                                                                                        '벽에 '
                                                                                                                                                                                        '붙일 '
                                                                                                                                                                                        '메모) '
                                                                                                                                                                                        'Scatter에서 '
                                                                                                                                                                                        '따로 '
                                                                                                                                                                                        '쓸 '
                                                                                                                                                                                        '수 '
                                                                                                                                                                                        '있어요. '
                                                                                                                                                                                        '비우면 '
                                                                                                                                                                                        '배치 '
                                                                                                                                                                                        '자체에 '
                                                                                                                                                                                        '남아요',
 'Build record not found: ': '빌드 기록을 찾을 수 없어요:',
 'Build record not found: %s': '빌드 기록을 찾을 수 없어요: {0}',
 'Builds a new source poster batch from the current list and settings. Previous build results are kept.': '지금 목록과 설정으로 새 원본 포스터 배치를 만들어요. 이전 결과는 그대로 둬요.',
 'Builds posters from several sources.': '여러 원본으로 포스터를 만들어요.',
 'Built %d posters / %d textures': '포스터 {0}장 / 텍스처 {1}장을 만들었어요',
 'Built-in paper textures ship with the addon. To use more of your own baked <name>_s<number>_normal.png textures, set that folder. If empty, only built-in textures are used.': '기본 '
                                                                                                                                                                                 '종이 '
                                                                                                                                                                                 '질감은 '
                                                                                                                                                                                 '애드온에 '
                                                                                                                                                                                 '들어 '
                                                                                                                                                                                 '있어요. '
                                                                                                                                                                                 '직접 '
                                                                                                                                                                                 '구운 '
                                                                                                                                                                                 '<이름>_s<번호>_normal.png '
                                                                                                                                                                                 '질감을 '
                                                                                                                                                                                 '더 '
                                                                                                                                                                                 '쓰려면 '
                                                                                                                                                                                 '그 '
                                                                                                                                                                                 '폴더를 '
                                                                                                                                                                                 '지정하세요. '
                                                                                                                                                                                 '비우면 '
                                                                                                                                                                                 '기본 '
                                                                                                                                                                                 '질감만 '
                                                                                                                                                                                 '써요.',
 'By Number': '번호순',
 'Cancel': '취소',
 'Cannot read the image.': '이미지를 읽을 수 없어요.',
 'Cannot read the image: ': '이미지를 읽을 수 없어요:',
 'Cannot read the image: %s': '이미지를 읽을 수 없어요: {0}',
 'Cap how many copies each poster gets, by poster size. Off repeats freely': '포스터 크기에 따라 복사 수에 상한을 둬요. 끄면 자유롭게 반복해요',
 'Caption': '손글씨 문구',
 'Caption  ·  ': '손글씨 문구  ·',
 'Caption  ·  %s': '손글씨 문구  ·  {0}',
 'Caption on %d card(s)': '카드 {0}장에 문구 넣음',
 'Caption on the photo card': '사진 카드의 손글씨 문구',
 'Caption removed from %d card(s)': '카드 {0}장에서 문구 지움',
 'Captions go on photo cards: pick a Format (e.g. Instant Mini) first': '손글씨 문구는 사진 카드에 들어가요: 먼저 형식(예: Instant Mini)을 고르세요',
 'Caption…': '손글씨 문구…',
 'Cells Used in Last Image': '마지막 이미지에 쓸 칸 수',
 'Center': '가운데',
 'Centered %d selected': '선택한 {0}장을 가운데로 모았어요',
 'Chance': '확률',
 'Chance to place a paper in each cell. Lower leaves random empty spots.': '각 칸에 종이를 붙일 확률. 낮추면 랜덤하게 빈 곳이 생겨요.',
 'Change it to get a different arrangement with the same settings': '같은 설정에서 다른 배치를 얻으려면 바꾸세요',
 'Changed to %s · poster sizes kept%s · Ctrl+Z to undo': '{0}(으)로 바꿨어요 · 포스터 크기 유지{1} · Ctrl+Z로 되돌리기',
 'Changes apply live (Live on)': '변경은 실시간으로 적용돼요 (실시간 켬)',
 'Check (or uncheck) every image: checked images go into the layout and the build': '모든 이미지를 체크(또는 해제)해요: 체크한 이미지가 레이아웃과 만들기에 들어가요',
 'Check All Images': '이미지 전체 체크',
 'Check images in the list (or select posters in the editor) first': '먼저 목록에서 이미지를 체크하세요 (또는 편집기에서 포스터 선택)',
 'Check the images to use with the checkboxes on the left of the list. Press Select All to use all of them.': '목록 왼쪽 체크박스로 사용할 이미지를 체크하세요. 전체 선택을 누르면 모두 써요.',
 'Checked images go into the layout and the build; Remove / Del, Group and Move to Cut use them too. Drag over the boxes for several. The blue row is the preview target.': '체크한 '
                                                                                                                                                                            '이미지가 '
                                                                                                                                                                            '레이아웃과 '
                                                                                                                                                                            '만들기에 '
                                                                                                                                                                            '들어가요. '
                                                                                                                                                                            '빼기 '
                                                                                                                                                                            '/ '
                                                                                                                                                                            'Del, '
                                                                                                                                                                            '그룹, '
                                                                                                                                                                            '자르기로 '
                                                                                                                                                                            '옮기기도 '
                                                                                                                                                                            '체크한 '
                                                                                                                                                                            '이미지에 '
                                                                                                                                                                            '적용돼요. '
                                                                                                                                                                            '여러 '
                                                                                                                                                                            '개는 '
                                                                                                                                                                            '상자 '
                                                                                                                                                                            '위를 '
                                                                                                                                                                            '드래그하세요. '
                                                                                                                                                                            '파란 '
                                                                                                                                                                            '줄은 '
                                                                                                                                                                            '미리보기 '
                                                                                                                                                                            '대상이에요.',
 'Choose a poster batch to re-edit, or select a built poster.': '다시 편집할 포스터 배치를 고르거나, 만든 포스터를 선택하세요.',
 'Choose a poster with effects first and press [Copy Effects]': '효과가 있는 포스터를 먼저 고르고 [효과 복사]를 누르세요',
 'Choose an effect above first. Apply after checking the preview.': '위에서 효과를 먼저 고르세요. 미리보기를 확인한 뒤 적용하세요.',
 'Classic': '클래식',
 'Classic 70s': '70년대 클래식',
 'Clear List': '목록 비우기',
 'Clear Name Selection': '이름 선택 해제',
 'Cleared %s effects': '{0} 효과를 지웠어요',
 'Cleared the list · Ctrl+Z to undo': '목록을 비웠어요 · Ctrl+Z로 되돌리기',
 'Clears the cut list. Source files are kept.': '자르기 목록을 비워요. 원본 파일은 그대로예요.',
 'Click Poster to Grab': '포스터 클릭해서 집기',
 'Click Wall to Place': '벽 클릭해서 붙이기',
 'Click a poster or a panel color cell · Esc to cancel': '포스터나 패널의 색 칸을 클릭하세요 · Esc 취소',
 'Click a poster to grab it · Esc cancel': '포스터를 클릭해서 집기 · Esc 취소',
 'Click a text on the selected image first': '선택한 이미지의 글자를 먼저 클릭하세요',
 'Click any poster on the wall to pick it up: it becomes a manual placement you can move (mouse), rotate (R) and scale (S). The other posters stay where they are': '벽의 '
                                                                                                                                                                    '포스터를 '
                                                                                                                                                                    '클릭해서 '
                                                                                                                                                                    '집어요: '
                                                                                                                                                                    '직접 '
                                                                                                                                                                    '배치로 '
                                                                                                                                                                    '바뀌어 '
                                                                                                                                                                    '마우스로 '
                                                                                                                                                                    '옮기고, '
                                                                                                                                                                    'R로 '
                                                                                                                                                                    '돌리고, '
                                                                                                                                                                    'S로 '
                                                                                                                                                                    '크기를 '
                                                                                                                                                                    '바꿀 '
                                                                                                                                                                    '수 '
                                                                                                                                                                    '있어요. '
                                                                                                                                                                    '다른 '
                                                                                                                                                                    '포스터는 '
                                                                                                                                                                    '그대로예요',
 'Click any poster on the wall · then move · R rotate · S scale': '벽의 포스터를 클릭 · 그다음 이동 · R 회전 · S 크기',
 'Click images on the canvas first · A selects all': '먼저 캔버스에서 이미지를 클릭하세요 · A = 전체 선택',
 'Click on empty space in the Poster Atlas sidebar: clear the name selection': 'Poster Atlas 사이드바 빈 곳 클릭: 이름 선택 해제',
 'Click on the wall to place. While placing: R rotate · S scale (then X width / Y or Z height) · +/- scale 10% · Ctrl snap · Esc cancel': '벽을 클릭해서 붙여요. 붙이는 중: '
                                                                                                                                          'R 회전 · S 크기 (다음 X '
                                                                                                                                          '가로 / Y나 Z 세로) · +/- '
                                                                                                                                          '10% 크기 · Ctrl 스냅 · '
                                                                                                                                          'Esc 취소',
 'Click the image whose size you want, then Shift+click the images to change (or A for all), then Copy Size': '원하는 크기의 이미지를 클릭하고, 바꿀 이미지를 Shift+클릭(또는 A로 전체)한 '
                                                                                                              '뒤 크기 복사를 누르세요',
 'Clips: origin at the grip, handle +Y up.': '집게: 원점은 집는 곳, 손잡이는 +Y 위.',
 'Close': '닫기',
 'Close Editor': '편집기 닫기',
 'Clothespin': '빨래집게',
 'Clothespin · Steel': '빨래집게 · 쇠',
 'Clothespin · Wood': '빨래집게 · 나무',
 'Coffee Ring': '커피 자국',
 'Collapse or Expand All': '모두 접기 / 펼치기',
 'Collection changed · press Reload': '컬렉션이 바뀌었어요 · 다시 불러오기를 누르세요',
 'Color': '색',
 'Color Adjust': '색 조정',
 'Color Random': '색 랜덤',
 'Color change cancelled.': '색 바꾸기를 취소했어요.',
 'Color set with eyedropper · #%02X%02X%02X': '스포이트로 색 지정 · #{0}{1}{2}',
 'Color, wear, holes and tears are set per image in that window.': '색, 마모, 구멍, 찢김은 그 창에서 이미지마다 정해요.',
 'Cols': '열',
 'Columns across each paper so it can follow a sideways curve (rails, round walls). 1 = no extra cuts. Raise for tight curves': '옆으로 휜 곡면(레일, 둥근 벽)을 따라가도록 종이를 '
                                                                                                                                '가로로 나누는 열 수. 1 = 추가로 안 나눔. 많이 '
                                                                                                                                '휜 곳은 올리세요',
 'Columns: how many even pieces each paper is cut into from left to right. Bends use these lines. The source is unchanged': '열: 종이를 왼쪽에서 오른쪽으로 몇 조각으로 나눌지. 이 '
                                                                                                                            '선을 따라 휘어요. 원본은 그대로예요',
 'Combine Individual Images': '개별 이미지 합치기',
 'Compile failed: ': '컴파일 실패:',
 'Compile failed: %s': '컴파일 실패: {0}',
 'Conform to Curve': '곡면 따라 붙이기',
 'Convert to Mesh': '메시로 변환',
 'Converted %d scatter(s) to mesh: ': '스캐터 {0}개를 메시로 변환:',
 'Converted %d scatter(s) to mesh: %s': '스캐터 {0}개를 메시로 변환: {1}',
 'Cool': '차갑게',
 'Cool Film': '차가운 필름',
 'Copied effects of #%d · choose other posters and [Paste]': '#{0} 효과를 복사했어요 · 다른 포스터를 고르고 [붙여넣기]',
 'Copy Effects': '효과 복사',
 'Copy Effects of #%d': '#{0} 효과 복사',
 'Copy Size': '크기 복사',
 'Copy Size  #%d': '크기 복사  #{0}',
 'Copy Size of #%d (%.0f × %.0f mm)': '#{0} 크기 복사 ({1} × {2} mm)',
 'Corner': '모서리',
 'Corner Chance': '모서리 확률',
 'Corner Focus': '모서리 집중',
 'Corner Size': '모서리 크기',
 'Corners': '모서리',
 'Could not find an optimal layout · try reducing the spacing.': '최적 배치를 찾지 못했어요 · 간격을 줄여 보세요.',
 'Could not find that poster source.': '그 포스터 원본을 찾지 못했어요.',
 'Could not read the color: %s': '색을 읽지 못했어요: {0}',
 'Count': '개수',
 'Count is an upper limit': '개수는 최대치예요',
 'Count linked + reuse: fills it all': '개수 연결 + 반복: 전부 채워요',
 'Count linked + reuse: fills the rail': '개수 연결 + 반복: 레일을 채워요',
 'Crease Wear': '구김 마모',
 'Crop': '자르기',
 'Crop applied · sizes are now based on the cropped photo.': '자르기를 적용했어요 · 이제 잘린 사진 기준으로 크기가 정해져요.',
 'Crop · lock frame to the entered size': '자르기 · 입력한 크기로 틀 고정',
 'Crumple': '구김',
 'Crumple %d': '구김 {0}',
 'Crumple Shading': '구김 음영',
 'Crumple Strength': '구김 강도',
 'Ctrl+A / Alt+A over the Poster Atlas sidebar: check / uncheck every image': 'Poster Atlas 사이드바 위에서 Ctrl+A / Alt+A: 모든 이미지 체크 / 해제',
 'Curl Angle': '말림 각도',
 'Curl angle (°) of the most curled poster. With random lift each poster scales between min and max.': '가장 많이 말린 포스터의 말림 각도(°). 랜덤 들뜸이면 포스터마다 최소~최대 사이로 바뀌어요.',
 'Curl like a Sticky Note': '스티키 노트처럼 말기',
 'Curve (1 ramp · 2 even · 3+ tip)': '곡선 (1 경사 · 2 고르게 · 3+ 끝)',
 'Curve Across': '가로 곡면',
 'Curve Down': '세로 곡면',
 'Curve Fit · Across': '곡면 맞춤 · 가로',
 'Curve Fit · Down': '곡면 맞춤 · 세로',
 'Curve Shape': '곡선 모양',
 'Curved Surface': '곡면',
 'Curved Surface Mode': '곡면 방식',
 'Curved surface': '곡면',
 'Custom': '직접',
 'Custom (pattern %d)': '직접 (무늬 {0})',
 'Custom Border': '테두리 직접 지정',
 'Custom Size (px)': '직접 크기 (px)',
 'Custom size': '직접 입력 크기',
 'Custom white border (mm) or print surface (roughness / metallic) for the selected pictures': '선택한 사진의 흰 테두리(mm) 직접 지정 또는 인화면(거칠기 / 금속성)',
 'Custom · %d': '직접 · {0}',
 'Custom…': '직접 입력…',
 'Cut': '자르기',
 'Cut #%d · undo it with × in the list on the right.': '#{0}을 잘랐어요 · 오른쪽 목록의 ×로 되돌릴 수 있어요.',
 'Cut Columns': '자르기 열',
 'Cut Images by Dragging': '드래그로 이미지 자르기',
 'Cut PNG Folder': '잘라낸 PNG 폴더',
 'Cut Rows': '자르기 행',
 'Cut Selected Image': '선택한 이미지 자르기',
 'Cut — draw a straight line across a poster  |  right-click to stop': '자르기 — 포스터를 가로지르는 직선을 그으세요  |  오른쪽 클릭으로 끝내기',
 'Damage': '손상',
 'Del / X over the Poster Atlas sidebar: remove the checked images (nothing checked: the highlighted one) from the open list. Source files are kept': 'Poster '
                                                                                                                                                      'Atlas '
                                                                                                                                                      '사이드바 '
                                                                                                                                                      '위에서 Del '
                                                                                                                                                      '/ X: '
                                                                                                                                                      '체크한 '
                                                                                                                                                      '이미지(없으면 '
                                                                                                                                                      '강조된 것)를 '
                                                                                                                                                      '열린 목록에서 '
                                                                                                                                                      '빼요. 원본 '
                                                                                                                                                      '파일은 '
                                                                                                                                                      '그대로예요',
 'Delete Text': '글자 지우기',
 'Depth (mm)': '깊이 (mm)',
 'Different random picks and spots': '랜덤 선택과 위치를 다르게',
 'Discarded paint on %d images.': '이미지 {0}장의 칠하기를 버렸어요.',
 'Distance between the surface and the lowest paper, so they never flicker into each other': '표면과 가장 아래 종이 사이 거리. 서로 깜빡이며 겹쳐 보이지 않게 해요',
 'Does not erase the paper; it reverts areas painted with this tool. Remove cuts with × in the list below.': '종이를 지우지 않고, 이 도구로 칠한 부분을 되돌려요. 자른 건 아래 목록의 ×로 '
                                                                                                             '지우세요.',
 'Down': '아래로',
 'Drag a collection from the Outliner here (or pick one): the checked images get it as their group': '아웃라이너에서 컬렉션을 여기로 끌어오거나 고르세요: 체크한 이미지가 그 그룹이 돼요',
 'Drag boxes · Click a box, Del / X: remove it · Wheel zoom · Middle button pan · Ctrl Z undo · Home frame all': '상자 드래그 · 상자 클릭 후 Del / X: 지우기 · 휠 확대 · 가운데 '
                                                                                                                 '버튼 이동 · Ctrl Z 되돌리기 · Home 전체 보기',
 'Drag empty space / B: box select · Shift click: add·remove · Shift + drag a handle: keep ratio · A: all · Alt A: none · Del: remove from layout · W: swap numbers (2 selected) / number by position (3+) · Arrow keys: move selection': '빈 '
                                                                                                                                                                                                                                          '곳 '
                                                                                                                                                                                                                                          '드래그 '
                                                                                                                                                                                                                                          '/ '
                                                                                                                                                                                                                                          'B: '
                                                                                                                                                                                                                                          '상자 '
                                                                                                                                                                                                                                          '선택 '
                                                                                                                                                                                                                                          '· '
                                                                                                                                                                                                                                          'Shift '
                                                                                                                                                                                                                                          '클릭: '
                                                                                                                                                                                                                                          '추가·빼기 '
                                                                                                                                                                                                                                          '· '
                                                                                                                                                                                                                                          'Shift '
                                                                                                                                                                                                                                          '+ '
                                                                                                                                                                                                                                          '손잡이 '
                                                                                                                                                                                                                                          '드래그: '
                                                                                                                                                                                                                                          '비율 '
                                                                                                                                                                                                                                          '유지 '
                                                                                                                                                                                                                                          '· '
                                                                                                                                                                                                                                          'A: '
                                                                                                                                                                                                                                          '전체 '
                                                                                                                                                                                                                                          '· '
                                                                                                                                                                                                                                          'Alt '
                                                                                                                                                                                                                                          'A: '
                                                                                                                                                                                                                                          '해제 '
                                                                                                                                                                                                                                          '· '
                                                                                                                                                                                                                                          'Del: '
                                                                                                                                                                                                                                          '레이아웃에서 '
                                                                                                                                                                                                                                          '빼기 '
                                                                                                                                                                                                                                          '· '
                                                                                                                                                                                                                                          'W: '
                                                                                                                                                                                                                                          '번호 '
                                                                                                                                                                                                                                          '바꾸기(2장) '
                                                                                                                                                                                                                                          '/ '
                                                                                                                                                                                                                                          '위치 '
                                                                                                                                                                                                                                          '순서 '
                                                                                                                                                                                                                                          '번호(3장+) '
                                                                                                                                                                                                                                          '· '
                                                                                                                                                                                                                                          '방향키: '
                                                                                                                                                                                                                                          '선택 '
                                                                                                                                                                                                                                          '이동',
 'Drag to move  ·  round knob = rotate  ·  corner square = size  ·  S / R / G keys too  ·  Alt ↑↓ line spacing  ·  Enter or double-click edit  ·  Del delete': '드래그로 '
                                                                                                                                                               '이동  '
                                                                                                                                                               '·  '
                                                                                                                                                               '동그란 '
                                                                                                                                                               '손잡이 '
                                                                                                                                                               '= '
                                                                                                                                                               '회전  '
                                                                                                                                                               '·  '
                                                                                                                                                               '모서리 '
                                                                                                                                                               '네모 '
                                                                                                                                                               '= '
                                                                                                                                                               '크기  '
                                                                                                                                                               '·  '
                                                                                                                                                               'S '
                                                                                                                                                               '/ '
                                                                                                                                                               'R '
                                                                                                                                                               '/ '
                                                                                                                                                               'G '
                                                                                                                                                               '키도 '
                                                                                                                                                               '돼요  '
                                                                                                                                                               '·  '
                                                                                                                                                               'Alt '
                                                                                                                                                               '↑↓ '
                                                                                                                                                               '줄 '
                                                                                                                                                               '간격  '
                                                                                                                                                               '·  '
                                                                                                                                                               'Enter '
                                                                                                                                                               '또는 '
                                                                                                                                                               '더블클릭으로 '
                                                                                                                                                               '수정  '
                                                                                                                                                               '·  '
                                                                                                                                                               'Del '
                                                                                                                                                               '삭제',
 'Draw a straight line across a poster to cut it cleanly along that line. The smaller side shown in red disappears.': '포스터를 가로지르는 직선을 그어 그 선을 따라 깔끔하게 잘라요. '
                                                                                                                      '빨간색으로 보이는 작은 쪽이 사라져요.',
 'Drop': '내림',
 'Drop Random': '내림 랜덤',
 'Drop a Collection': '컬렉션 놓기',
 'Each corner by chance (some posters get one, some two...)': '모서리마다 확률로 (어떤 포스터는 1개, 어떤 건 2개...)',
 'Each one a bit bigger or smaller': '하나씩 조금 크거나 작게',
 'Each paper adds a random amount between minus and plus this around world X': '종이마다 월드 X축으로 ± 이 값 사이의 랜덤 회전을 더해요',
 'Each paper adds a random amount between minus and plus this around world Y': '종이마다 월드 Y축으로 ± 이 값 사이의 랜덤 회전을 더해요',
 'Each paper adds a random amount between minus and plus this around world Z': '종이마다 월드 Z축으로 ± 이 값 사이의 랜덤 회전을 더해요',
 'Each paper adds a random amount between minus and plus this, drawn separately for every axis that is on': '종이마다 켜진 축별로 따로 ± 이 값 사이의 랜덤 회전을 더해요',
 'Each paper is scaled randomly between 1 minus and 1 plus this, around its source pivot. 0.2 gives 0.8 to 1.2 times': '종이마다 원본 피벗을 중심으로 1 빼기 ~ 1 더하기 이 값 사이에서 '
                                                                                                                       '랜덤 크기. 0.2면 0.8~1.2배',
 'Each paper overlaps the one before it': '종이마다 앞 종이를 덮어요',
 'Each paper tucks under the one before it': '종이마다 앞 종이 밑으로 들어가요',
 'Each poster is held one way only (all tape, or all pins) and how many depends on its size: small ones often 1, big ones 2 to 4. Kind = object name before _ (TAPE_..., PIN_...) or a pin_kind property': '포스터마다 '
                                                                                                                                                                                                           '한 '
                                                                                                                                                                                                           '가지 '
                                                                                                                                                                                                           '방식만(전부 '
                                                                                                                                                                                                           '테이프 '
                                                                                                                                                                                                           '또는 '
                                                                                                                                                                                                           '전부 '
                                                                                                                                                                                                           '핀) '
                                                                                                                                                                                                           '쓰고 '
                                                                                                                                                                                                           '개수는 '
                                                                                                                                                                                                           '크기에 '
                                                                                                                                                                                                           '따라: '
                                                                                                                                                                                                           '작은 '
                                                                                                                                                                                                           '건 '
                                                                                                                                                                                                           '보통 '
                                                                                                                                                                                                           '1개, '
                                                                                                                                                                                                           '큰 '
                                                                                                                                                                                                           '건 '
                                                                                                                                                                                                           '2~4개. '
                                                                                                                                                                                                           '종류 '
                                                                                                                                                                                                           '= '
                                                                                                                                                                                                           '오브젝트 '
                                                                                                                                                                                                           '이름의 '
                                                                                                                                                                                                           '_ '
                                                                                                                                                                                                           '앞부분 '
                                                                                                                                                                                                           '(TAPE_..., '
                                                                                                                                                                                                           'PIN_...) '
                                                                                                                                                                                                           '또는 '
                                                                                                                                                                                                           'pin_kind '
                                                                                                                                                                                                           '속성',
 'Each poster lifts a random amount between the minimum and the maximum': '포스터마다 최소~최대 사이에서 랜덤하게 들려요',
 'Each poster picks one from the ink palette': '포스터마다 잉크 팔레트에서 하나씩 골라요',
 'Each poster picks one from the palette': '포스터마다 팔레트에서 하나씩 골라요',
 'Edge Depth mm': '가장자리 깊이 mm',
 'Edge Lift': '가장자리 들뜸',
 'Edge Softness': '가장자리 부드러움',
 'Edge Wear Random': '가장자리 마모 랜덤',
 'Edge Width (mm)': '가장자리 폭 (mm)',
 'Edge Width mm': '가장자리 폭 mm',
 'Edge select mode hangs along edges': '변 선택 모드면 변을 따라 걸어요',
 'Edit': '편집',
 'Edit Cut List': '자르기 목록 편집',
 'Edit Image List': '이미지 목록 편집',
 'Edit Mode': '편집 모드',
 'Edit Palette': '팔레트 편집',
 'Edit Repeat Range': '반복 구간 편집',
 'Editing %s · Build updates it': '{0} 편집 중 · 만들기로 업데이트',
 'Editor closed · unbuilt changes were not saved.': '편집기를 닫았어요 · 만들지 않은 변경은 저장되지 않았어요.',
 'Effect Details': '효과 세부 설정',
 'Effects  ·  %d selected': '효과  ·  {0}장 선택',
 'Empty = automatic (Batch N · groups)': '비우면 자동 (배치 N · 그룹)',
 'Empty name = no group.': '이름을 비우면 그룹 없음.',
 'Enable Paper Lift · Bend': '종이 들뜸 · 휨 켜기',
 'End Margin': '끝 여백',
 'Enter Size Manually': '크기 직접 입력',
 'Erase': '지우기',
 'Error re-reading sources: ': '원본을 다시 읽다 오류:',
 'Error re-reading sources: %s': '원본을 다시 읽다 오류: {0}',
 'Every corner': '모든 모서리',
 'Every other column sits a little lower, like some photo booth strips': '한 열 건너 하나씩 조금 아래로, 일부 포토부스 스트립처럼',
 'Exclude Cell Inner Margin (px)': '칸 안쪽 여백 제외 (px)',
 'Excluded non-flat sources: ': '평평하지 않아 제외된 원본:',
 'Excluded non-flat sources: %s': '평평하지 않아 제외된 원본: {0}',
 'Excludes this many pixels from each of the four edges of each cell in the source image.': '원본 이미지의 각 칸 네 변에서 이만큼 픽셀을 빼요.',
 'Expired': '유통기한 지난 필름',
 'Extra Folder': '추가 폴더',
 'Extra Paper Texture Folder': '추가 종이 질감 폴더',
 'Extra random turn per object': '오브젝트마다 추가 랜덤 회전',
 'Extra stretch across (S then X while placing)': '가로로 더 늘리기 (붙이는 중 S 다음 X)',
 'Extra stretch up-down (S then Y or Z while placing)': '위아래로 더 늘리기 (붙이는 중 S 다음 Y 또는 Z)',
 'Eyedropper': '스포이트',
 'Eyedropper (%s): click a poster or a color cell · Esc = Cancel': '스포이트 ({0}): 포스터나 색 칸을 클릭하세요 · Esc = 취소',
 'Fade': '바램',
 'Fade Color': '색 바래기',
 'Faded Sun': '햇빛 바램',
 'Fades and blurs color as if scratched.': '긁힌 것처럼 색이 바래고 흐려져요.',
 'Fiber Length (mm)': '섬유 길이 (mm)',
 'Fiber Length mm': '섬유 길이 mm',
 'Fiber Rim': '섬유 테두리',
 'File not found: ': '파일을 찾을 수 없어요:',
 'File not found: %s': '파일을 찾을 수 없어요: {0}',
 'Fill': '채움',
 'Fill All': '전체 채우기',
 'Fill Current Paint': '지금 칠 전체 채우기',
 'Fill Empty Space': '빈 곳 채우기',
 'Fill Gaps': '빈틈 채우기',
 'Fill with the photo, then drag to choose the crop': '사진으로 채운 뒤 드래그해서 잘릴 부분을 고르세요',
 'Fills the frame; move the photo inside to choose what gets cropped.': '틀을 꽉 채워요. 틀 안에서 사진을 움직여 잘릴 부분을 고르세요.',
 'Find Cells by Green': '초록으로 칸 찾기',
 'Finish': '마무리',
 'Finish  ·  whole layout': '마무리  ·  레이아웃 전체',
 'Finish Painting': '칠하기 끝내기',
 'Finish painting and return to the view and mode from before': '칠하기를 끝내고 이전 뷰와 모드로 돌아가요',
 'Finish the current placement first.': '지금 붙이는 걸 먼저 끝내세요.',
 'Finish: turn it into a mesh': '마무리: 메시로 바꾸기',
 'Firm': '세게',
 'First set the "Extra Paper Texture Folder" to store baked textures. Built-in textures ship with the addon.': '먼저 구운 질감을 넣을 "추가 종이 질감 폴더"를 지정하세요. 기본 질감은 애드온에 '
                                                                                                               '들어 있어요.',
 'Fixed rotation around X': 'X축 고정 회전',
 'Fixed rotation around Y': 'Y축 고정 회전',
 'Fixed rotation around Z': 'Z축 고정 회전',
 'Fixed rotation around every axis that is on': '켜진 축마다 고정 회전',
 'Fixed rotation around world X': '월드 X축 고정 회전',
 'Fixed rotation around world Y': '월드 Y축 고정 회전',
 'Fixed rotation around world Z': '월드 Z축 고정 회전',
 'Flat poster planes, e.g. from Poster Atlas': '평평한 포스터 면, 예: Poster Atlas에서 만든 것',
 'Fold Size': '접힘 크기',
 'Fold or unfold every section of the Poster Scatter panel at once': 'Poster Scatter 패널의 모든 섹션을 한꺼번에 접거나 펼쳐요',
 'Follow the poster X rotation (tilt forward / back)': '포스터의 X 회전 따라가기 (앞뒤 기울기)',
 'Follow the poster Y rotation (side lean)': '포스터의 Y 회전 따라가기 (옆 기울기)',
 'Follow the poster Z rotation (turn on the wall)': '포스터의 Z 회전 따라가기 (벽 위 회전)',
 'Font': '글꼴',
 'Fonts': '글꼴',
 'For Cutting': '자르기용',
 'For Textures': '텍스처용',
 'Found %d on the green background': '초록 배경에서 {0}개 찾음',
 'From 0 px · arrow buttons move the selected images': '0 px부터 · 화살표 버튼으로 선택한 이미지를 옮겨요',
 'Full Top': '위 전체',
 'Gap': '간격',
 'Gap Between Papers': '종이 사이 간격',
 'Gap between overlapping surfaces. Tilted or lifted papers get extra height so they never intersect.': '겹친 면 사이 간격. 기울거나 들뜬 종이는 높이를 더 줘서 절대 파고들지 않아요.',
 'Gentle': '살살',
 'Get Started': '시작하기',
 'Give the checked images a group. Build puts each group in its own collection inside the batch (e.g. Photos for the string, Notes for the wall), so Scatter can use them separately. X clears it': '체크한 '
                                                                                                                                                                                                    '이미지에 '
                                                                                                                                                                                                    '그룹을 '
                                                                                                                                                                                                    '줘요. '
                                                                                                                                                                                                    '만들기를 '
                                                                                                                                                                                                    '하면 '
                                                                                                                                                                                                    '그룹마다 '
                                                                                                                                                                                                    '배치 '
                                                                                                                                                                                                    '안에 '
                                                                                                                                                                                                    '자기 '
                                                                                                                                                                                                    '컬렉션이 '
                                                                                                                                                                                                    '생겨서(예: '
                                                                                                                                                                                                    '끈에 '
                                                                                                                                                                                                    '걸 '
                                                                                                                                                                                                    '사진, '
                                                                                                                                                                                                    '벽에 '
                                                                                                                                                                                                    '붙일 '
                                                                                                                                                                                                    '메모) '
                                                                                                                                                                                                    'Scatter에서 '
                                                                                                                                                                                                    '따로 '
                                                                                                                                                                                                    '쓸 '
                                                                                                                                                                                                    '수 '
                                                                                                                                                                                                    '있어요. '
                                                                                                                                                                                                    'X로 '
                                                                                                                                                                                                    '지워요',
 'Glossy': '유광',
 'Glue strip at the top stays on the wall, the rest lifts off and curls a little at the bottom, a different amount on each note': '위쪽 접착 부분은 벽에 붙어 있고 나머지는 떨어져 '
                                                                                                                                  '아래가 조금 말려요. 노트마다 정도가 달라요',
 'Glued Top / Bend Start': '접착 위쪽 / 휨 시작',
 'Goes into: ': '들어갈 곳:',
 'Goes into:  %s  ›  %s': '들어갈 곳:  {0}  ›  {1}',
 'Goes into: %s': '들어갈 곳: {0}',
 'Graph not found.': '그래프를 찾을 수 없어요.',
 'Green Inset': '초록 안쪽 여백',
 'Green inset %d px%s': '초록 안쪽 여백 {0} px{1}',
 'Green trim: cut this many extra pixels inside every edge (removes the green fringe)': '초록 잘라내기: 모든 변에서 이만큼 픽셀을 더 안쪽으로 잘라요 (초록 테두리 제거)',
 'Grid Paper': '모눈종이',
 'Group': '그룹',
 'Group "%s" → "%s" · %d image(s)': '그룹 "{0}" → "{1}" · 이미지 {2}장',
 'Group %d': '그룹 {0}',
 'Group %d image%s': '이미지 {0}장 그룹 지정',
 'Group Checked Images': '체크한 이미지를 그룹으로',
 'Groups': '그룹',
 'Groups: ': '그룹:',
 'Groups: %s': '그룹: {0}',
 'Guide': '안내',
 'HEIGHT (Y/Z)': '세로 (Y/Z)',
 'Hand Painted': '손으로 칠함',
 'Handwriting': '손글씨',
 'Hang': '걸기',
 'Hang along ': '따라 걸기:',
 'Hang along %s': '{0} 따라 걸기',
 'Hang along a curve or edges': '커브나 변을 따라 걸기',
 'Hang along the edges of ': '변을 따라 걸기:',
 'Hang along the edges of %s': '{0}의 변을 따라 걸기',
 'Hang along the selected edges': '선택한 변을 따라 걸기',
 'Hang papers along a curve or mesh edges, like order tickets on a rail or notes on a string': '커브나 메시 변을 따라 종이를 걸어요. 레일의 주문서나 끈에 건 메모처럼',
 'Hang posters along the selected curve, or the selected edges in Edit Mode. Select several strings to hang along all of them (they are joined into one line). No wall area is needed: an invisible one is made under the rail and follows it': '선택한 '
                                                                                                                                                                                                                                                '커브, '
                                                                                                                                                                                                                                                '또는 '
                                                                                                                                                                                                                                                '편집 '
                                                                                                                                                                                                                                                '모드에서 '
                                                                                                                                                                                                                                                '선택한 '
                                                                                                                                                                                                                                                '변을 '
                                                                                                                                                                                                                                                '따라 '
                                                                                                                                                                                                                                                '포스터를 '
                                                                                                                                                                                                                                                '걸어요. '
                                                                                                                                                                                                                                                '끈을 '
                                                                                                                                                                                                                                                '여러 '
                                                                                                                                                                                                                                                '개 '
                                                                                                                                                                                                                                                '선택하면 '
                                                                                                                                                                                                                                                '모두 '
                                                                                                                                                                                                                                                '따라 '
                                                                                                                                                                                                                                                '걸어요(하나의 '
                                                                                                                                                                                                                                                '선으로 '
                                                                                                                                                                                                                                                '합쳐져요). '
                                                                                                                                                                                                                                                '벽 '
                                                                                                                                                                                                                                                '영역은 '
                                                                                                                                                                                                                                                '필요 '
                                                                                                                                                                                                                                                '없어요: '
                                                                                                                                                                                                                                                '레일 '
                                                                                                                                                                                                                                                '아래에 '
                                                                                                                                                                                                                                                '보이지 '
                                                                                                                                                                                                                                                '않는 '
                                                                                                                                                                                                                                                '영역이 '
                                                                                                                                                                                                                                                '만들어져 '
                                                                                                                                                                                                                                                '따라가요',
 'Hard': '딱딱하게',
 'Heavy': '아주 굵게',
 'Height': '세로',
 'Height (mm)': '세로 (mm)',
 'Hide Picked Plane in Render': '렌더에서 고른 평면 숨기기',
 'Hide Source Face in Render': '렌더에서 원본 면 숨기기',
 'Hide These Posters': '이 포스터 숨기기',
 'Hides the plane picked when creating the area from renders. The scatter area keeps its own copy of the shape, so placement is not affected. Turn this off if you created it from the wall itself.': '영역을 '
                                                                                                                                                                                                      '만들 '
                                                                                                                                                                                                      '때 '
                                                                                                                                                                                                      '고른 '
                                                                                                                                                                                                      '평면을 '
                                                                                                                                                                                                      '렌더에서 '
                                                                                                                                                                                                      '숨겨요. '
                                                                                                                                                                                                      '영역이 '
                                                                                                                                                                                                      '모양을 '
                                                                                                                                                                                                      '따로 '
                                                                                                                                                                                                      '복사해 '
                                                                                                                                                                                                      '두기 '
                                                                                                                                                                                                      '때문에 '
                                                                                                                                                                                                      '배치에는 '
                                                                                                                                                                                                      '영향이 '
                                                                                                                                                                                                      '없어요. '
                                                                                                                                                                                                      '벽 '
                                                                                                                                                                                                      '자체로 '
                                                                                                                                                                                                      '만들었다면 '
                                                                                                                                                                                                      '끄세요.',
 'Higher values mix posters without holes and heavily punched ones.': '높을수록 구멍 없는 포스터와 많이 뚫린 포스터가 섞여요.',
 'Hole Amount': '구멍 양',
 'Hole Random': '구멍 랜덤',
 'Hole Size mm': '구멍 크기 mm',
 'Hole White Rim': '구멍 흰 테두리',
 'Holes': '구멍',
 'Holes Adjust': '구멍 조정',
 'Horizontal': '가로',
 'Horizontal Divisions': '가로 분할',
 'Hover over a poster or color cell and press E.': '포스터나 색 칸 위에 마우스를 두고 E를 누르세요.',
 'How far below the rail the top edge sits. Negative tucks the top above the line (behind a clip or lip)': '윗변이 레일보다 얼마나 아래에 오는지. 음수면 윗부분이 선 위로 올라가요 (집게나 턱 '
                                                                                                           '뒤로)',
 'How far in from the very corner the tape sits (0 = centred on the corner)': '모서리 끝에서 테이프가 얼마나 안쪽에 붙는지 (0 = 모서리 중앙)',
 'How far papers drift from the grid. Higher looks more natural.': '종이가 격자에서 벗어나는 정도. 높을수록 자연스러워요.',
 'How far the rise spreads from an overlap into the rest of the paper. 0 bends right at the lower edge, higher ramps more gently': '겹친 곳에서 올라간 부분이 종이 나머지로 퍼지는 '
                                                                                                                                   '정도. 0이면 아래 가장자리에서 바로 꺾이고, '
                                                                                                                                   '높을수록 완만해요',
 'How far the torn line wiggles inward. The pattern size scales with this too.': '찢긴 선이 안쪽으로 구불거리는 정도예요. 무늬 크기도 같이 바뀌어요.',
 'How hard covered papers are pressed flat. Up to 0.4 flattens the covered parts; above that, any covered paper is pressed as a whole and is completely flat at 1.': '덮인 '
                                                                                                                                                                     '종이를 '
                                                                                                                                                                     '얼마나 '
                                                                                                                                                                     '평평하게 '
                                                                                                                                                                     '누를지. '
                                                                                                                                                                     '0.4까지는 '
                                                                                                                                                                     '덮인 '
                                                                                                                                                                     '부분만 '
                                                                                                                                                                     '평평해지고, '
                                                                                                                                                                     '그 '
                                                                                                                                                                     '이상은 '
                                                                                                                                                                     '덮인 '
                                                                                                                                                                     '종이 '
                                                                                                                                                                     '전체를 '
                                                                                                                                                                     '눌러 '
                                                                                                                                                                     '1이면 '
                                                                                                                                                                     '완전히 '
                                                                                                                                                                     '평평해요.',
 'How many group buttons the Layout Editor shows': '레이아웃 편집기에 보일 그룹 버튼 개수',
 'How many per poster (random placements)': '포스터마다 몇 개 (랜덤 위치)',
 'How many posters to place at most. Fewer are placed if space runs out. Typing a number unlinks it from the poster count': '최대로 붙일 포스터 수. 공간이 부족하면 더 적게 붙어요. '
                                                                                                                            '숫자를 직접 입력하면 포스터 수 연결이 풀려요',
 'How much each paper covers the next, as a share of its width. Negative leaves gaps: -1 = a gap one paper wide, -3 = three papers wide': '종이가 다음 종이를 덮는 정도 (폭 '
                                                                                                                                          '대비). 음수면 틈이 생겨요: -1 '
                                                                                                                                          '= 종이 한 장 너비, -3 = 세 '
                                                                                                                                          '장 너비',
 'How much it lifts': '얼마나 들뜰지',
 'How much neighbors overlap. 0 means touching, higher overlaps more. Negative leaves gaps.': '이웃끼리 겹치는 정도. 0이면 맞닿고, 높을수록 많이 겹쳐요. 음수면 틈이 생겨요.',
 'How much pressing weakens the deeper a paper is buried. 1 is the same at any depth; lower keeps the original shape of deep papers.': '종이가 깊이 묻힐수록 누르는 힘이 '
                                                                                                                                       '약해지는 정도. 1이면 깊이와 상관없이 '
                                                                                                                                       '같고, 낮을수록 깊은 종이의 원래 모양이 '
                                                                                                                                       '남아요.',
 'How much the print has faded in sunlight.': '인쇄가 햇빛에 바랜 정도예요.',
 'How much the print peels off to reveal paper.': '인쇄가 벗겨져 종이가 드러나는 정도예요.',
 'How the bottom bends: 1 = straight ramp from the bend line, 2 = even curve, higher = stays flat longer and curls at the tip (sticky note)': '아랫부분이 휘는 모양: 1 '
                                                                                                                                              '= 휨 선에서 곧은 경사, '
                                                                                                                                              '2 = 고른 곡선, 높을수록 '
                                                                                                                                              '오래 평평하다가 끝에서 '
                                                                                                                                              '말려요 (스티키 노트)',
 'Hue Shift': '색조 이동',
 'Hung %d poster%s along %s.': '{2}을(를) 따라 포스터 {0}장을 걸었어요.',
 'If empty, looks in the default install location.': '비우면 기본 설치 위치에서 찾아요.',
 'Image Cutting · %d': '이미지 자르기 · {0}',
 'Image Preview · %d / %d': '이미지 미리보기 · {0} / {1}',
 'Image files dropped on the Poster Atlas sidebar go into the list of the open tab (Textures or Cut)': 'Poster Atlas 사이드바에 놓은 이미지 파일은 열린 탭(텍스처 또는 자르기)의 목록에 '
                                                                                                       '들어가요',
 'Image list restored (%d images).': '이미지 목록을 되돌렸어요 ({0}장).',
 'Image preview: Wheel = Zoom / Middle button = Pan / ← → = Previous·Next / Enter or Esc = Close': '이미지 미리보기: 휠 = 확대 / 가운데 버튼 = 이동 / ← → = 이전·다음 / Enter 또는 '
                                                                                                   'Esc = 닫기',
 'Images': '이미지',
 'Images overlap. Please move them slightly.': '이미지가 겹쳐요. 조금씩 옮겨 주세요.',
 'Images to Cut': '자를 이미지',
 'Images to turn into poster textures': '포스터 텍스처로 만들 이미지',
 'Ink': '잉크',
 'Ink %d': '잉크 {0}',
 'Ink Color Preset': '잉크 색 프리셋',
 'Ink Color Strength': '잉크 색 강도',
 'Ink color': '잉크 색',
 'Ink color (black areas)': '잉크 색 (검은 부분)',
 'Ink color (dark areas)': '잉크 색 (어두운 부분)',
 'Input Mode': '입력 방식',
 'Inset': '안쪽 거리',
 'Inset %d px': '안쪽 여백 {0} px',
 'Instant Classic 4.5 / 6.5 / 21.5 · Mini/Square/Wide 4 / 6.5 / 17.5': 'Instant Classic 4.5 / 6.5 / 21.5 · Mini/Square/Wide 4 / 6.5 / 17.5',
 'Internal (older name selection, no longer shown)': '내부용 (예전 이름 선택, 더 이상 표시 안 함)',
 'Invalid crop data.': '자르기 데이터가 잘못됐어요.',
 'Invalid layout rotation data.': '레이아웃 회전 데이터가 잘못됐어요.',
 'Invert': '반전',
 'Invert Paint': '칠 반전',
 'Inverts the visible paint: painted <-> unpainted (for the placeable mask, where posters go and where they do not swap)': '보이는 칠을 반전해요: 칠함 <-> 안 칠함 (붙일 수 있는 '
                                                                                                                           '마스크라면 붙는 곳과 안 붙는 곳이 바뀌어요)',
 'Jitter': '흐트러짐',
 'Job Name': '작업 이름',
 'Keep Backup': '백업 유지',
 'Keep Each Pattern': '무늬 각각 유지',
 'Keep Flat': '평평하게 유지',
 'Keep Ratio': '비율 유지',
 'Keep Ratio · show the whole photo': '비율 유지 · 사진 전체 보이기',
 'Keep the original scatter hidden so it can be edited again later': '원래 스캐터를 숨겨 두어 나중에 다시 고칠 수 있게 해요',
 "Keeps each image's hole and tear positions even when changing several together.": '여러 개를 같이 바꿔도 이미지마다 구멍과 찢김 위치를 유지해요.',
 'Keeps papers this far from both ends of an open rail (away from the nails / hooks it hangs from)': '열린 레일의 양 끝에서 종이를 이만큼 떨어뜨려요 (걸어 둔 못·고리에서 떨어지게)',
 'Keeps the layout and changes only the lift.': '배치는 그대로 두고 들뜸만 바꿔요.',
 'Keeps the source objects and IDs of the same images and updates meshes and textures. Existing sources removed from the list are kept.': '같은 이미지의 원본 오브젝트와 '
                                                                                                                                          'ID는 유지하고 메시와 텍스처를 '
                                                                                                                                          '업데이트해요. 목록에서 빠진 기존 '
                                                                                                                                          '원본은 그대로 둬요.',
 'Kinds: ': '종류:',
 'Kinds: %s': '종류: {0}',
 'Kraft Texture': '크라프트 질감',
 'Kraft·Recycled': '크라프트·재생지',
 'Large': '크게',
 'Larger = sharper, but bigger files and slower': '클수록 선명하지만 파일이 커지고 느려져요',
 'Lay posters over the layers below (including lifted shapes) without intersecting them': '아래 레이어(들뜬 모양 포함) 위에 겹치지 않게 얹어요',
 'Layer %d · %s': '레이어 {0} · {1}',
 'Layer %d: placed %d poster%s %s': '레이어 {0}: 포스터 {1}장 붙임 {3}',
 'Layers': '레이어',
 'Layers the paper texture onto poster materials. Materials that already have it are updated to the current settings.': '포스터 재질에 종이 질감을 겹쳐요. 이미 있는 재질은 지금 설정으로 '
                                                                                                                        '업데이트돼요.',
 'Layout': '레이아웃',
 'Layout  ·  %d × %d': '레이아웃  ·  {0} × {1}',
 'Layout Editor  ·  Build': '레이아웃 편집기  ·  만들기',
 'Layout Settings': '레이아웃 설정',
 'Layout Tab': '레이아웃 탭',
 'Layout count does not match the image count.': '레이아웃 개수가 이미지 개수와 맞지 않아요.',
 'Layout: how papers spread out': '레이아웃: 종이를 펼치는 방식',
 'Left 90°  (Q)': '왼쪽 90°  (Q)',
 'Left and right lift together': '왼쪽과 오른쪽이 함께 들려요',
 'Left click place · R rotate · S scale (then X / Y / Z for one axis) · +/- scale 10% · 0 reset · Esc cancel': '왼쪽 클릭 붙이기 · R 회전 · S 크기 (다음 X / Y / Z로 한 축만) · '
                                                                                                               '+/- 10% 크기 · 0 초기화 · Esc 취소',
 'Left · right': '왼쪽 · 오른쪽',
 'Less rotation packs tighter': '회전이 적을수록 빽빽하게 들어가요',
 'Let posters cover each other a little (Random and Fill Gaps). Overlap Grid and Along Rail always overlap': '포스터끼리 조금 덮도록 해요 (랜덤, 빈틈 채우기). 겹친 격자와 레일 따라는 항상 '
                                                                                                             '겹쳐요',
 'Let the automatic posters be laid out again around your manual posters (undo the "keep where they are" from grabbing)': '직접 붙인 포스터 주변으로 자동 포스터를 다시 배치해요 (집을 '
                                                                                                                          "때의 '제자리 유지'를 풀어요)",
 'Lift Height (%)': '들뜸 높이 (%)',
 'Lift Off Paper': '종이에서 띄우기',
 'Lift Random Seed': '들뜸 랜덤 시드',
 'Lift Ratio': '들뜸 비율',
 'Lift Seed': '들뜸 시드',
 'Lift Start': '들뜸 시작',
 'Lift as a ratio of the poster height. At 5%, a 100 mm tall paper lifts up to 5 mm. Limited so it never exceeds the bending length. Negative values bend backward: on floors the curled edges rest on the floor and the middle rises, on a line the paper curls away': '포스터 '
                                                                                                                                                                                                                                                                        '높이 '
                                                                                                                                                                                                                                                                        '대비 '
                                                                                                                                                                                                                                                                        '들뜸. '
                                                                                                                                                                                                                                                                        '5%면 '
                                                                                                                                                                                                                                                                        '높이 '
                                                                                                                                                                                                                                                                        '100 '
                                                                                                                                                                                                                                                                        'mm '
                                                                                                                                                                                                                                                                        '종이가 '
                                                                                                                                                                                                                                                                        '최대 '
                                                                                                                                                                                                                                                                        '5 '
                                                                                                                                                                                                                                                                        'mm '
                                                                                                                                                                                                                                                                        '들려요. '
                                                                                                                                                                                                                                                                        '휘는 '
                                                                                                                                                                                                                                                                        '길이를 '
                                                                                                                                                                                                                                                                        '넘지 '
                                                                                                                                                                                                                                                                        '않게 '
                                                                                                                                                                                                                                                                        '제한돼요. '
                                                                                                                                                                                                                                                                        '음수면 '
                                                                                                                                                                                                                                                                        '뒤로 '
                                                                                                                                                                                                                                                                        '휘어요: '
                                                                                                                                                                                                                                                                        '바닥에서는 '
                                                                                                                                                                                                                                                                        '말린 '
                                                                                                                                                                                                                                                                        '가장자리가 '
                                                                                                                                                                                                                                                                        '바닥에 '
                                                                                                                                                                                                                                                                        '닿고 '
                                                                                                                                                                                                                                                                        '가운데가 '
                                                                                                                                                                                                                                                                        '올라오고, '
                                                                                                                                                                                                                                                                        '선에서는 '
                                                                                                                                                                                                                                                                        '종이가 '
                                                                                                                                                                                                                                                                        '반대로 '
                                                                                                                                                                                                                                                                        '말려요',
 'Light': '약하게',
 'Lime': '연두',
 'Limit 0 keeps that size out': '제한 0이면 그 크기는 빠져요',
 'Limit Copies by Size': '크기별 복사 수 제한',
 'Line ×%.1f': '줄 간격 ×{0}',
 'Lined Note': '줄 노트',
 'Linen Paper': '린넨 종이',
 'Link Count to Posters': '개수를 포스터 수에 연결',
 'Link to Poster Scatter': 'Poster Scatter에 연결',
 'Linked the source collection. Select a wall and create an area in the Poster Scatter tab.': '원본 컬렉션을 연결했어요. 벽을 선택하고 Poster Scatter 탭에서 영역을 만드세요.',
 'List': '목록',
 'Live': '실시간',
 'Live Preview': '실시간 미리보기',
 'Live paused by the error': '오류로 실시간 멈춤',
 'Load Preset': '프리셋 불러오기',
 'Loaded values of #%d.': '#{0} 값을 불러왔어요.',
 'Locks the paper color of the selected source posters and their placed copies to the color above. Other posters are unaffected.': '선택한 원본 포스터와 벽에 붙인 복사본의 종이 '
                                                                                                                                   '색을 위의 색으로 고정해요. 다른 포스터는 영향 '
                                                                                                                                   '없어요.',
 'Look: %s · %d image(s)': '룩: {0} · 이미지 {1}장',
 'Low = shiny coated paper, high = plain matte paper. Glossy 0.25 · Silk 0.4 · Satin 0.55 · Matte 0.85': '낮을수록 반짝이는 코팅지, 높을수록 무광 종이. 유광 0.25 · 실크 0.4 · 새틴 '
                                                                                                         '0.55 · 무광 0.85',
 'Low = shiny glossy print, high = matte. Matte 0.62 · Satin 0.45 · Silk 0.35 · Glossy 0.18': '낮을수록 반짝이는 유광 인화, 높을수록 무광. 무광 0.62 · 새틴 0.45 · 실크 0.35 · 유광 0.18',
 'Made from part of %s · it stays in renders': '{0}의 일부로 만듦 · 렌더에 그대로 보여요',
 'Make %d-Cut  ·  %s card  (%d selected)': '{0}컷 만들기  ·  {1} 카드  (선택 {2}장)',
 'Make a clothespin object at the 3D cursor and use it on these posters. Move, edit or copy it like any object': '3D 커서 위치에 빨래집게 오브젝트를 만들어 이 포스터들에 써요. 다른 '
                                                                                                                 '오브젝트처럼 옮기고 고치고 복사할 수 있어요',
 'Make a scatter area on the selected wall or floor. Edit Mode uses the selected faces, Object Mode uses all faces. Poles and curved walls work too': '선택한 벽이나 '
                                                                                                                                                      '바닥에 스캐터 '
                                                                                                                                                      '영역을 '
                                                                                                                                                      '만들어요. '
                                                                                                                                                      '편집 모드면 '
                                                                                                                                                      '선택한 면, '
                                                                                                                                                      '오브젝트 '
                                                                                                                                                      '모드면 모든 '
                                                                                                                                                      '면을 써요. '
                                                                                                                                                      '기둥과 둥근 '
                                                                                                                                                      '벽도 돼요',
 'Makes a normal mesh (final step)': '일반 메시로 만들어요 (마지막 단계)',
 'Mask': '마스크',
 'Match Poster Size': '포스터 크기에 맞추기',
 'Matte': '무광',
 'Matte 0.62 · Satin 0.45 · Silk 0.35 · Glossy 0.18 · Metallic 0': '무광 0.62 · 새틴 0.45 · 실크 0.35 · 유광 0.18 · 금속성 0',
 'Matte 0.85 · Satin 0.55 · Silk 0.4 · Glossy 0.25': '무광 0.85 · 새틴 0.55 · 실크 0.4 · 유광 0.25',
 'Max ': '최대',
 'Max %s': '최대 {0}',
 'Max Count': '최대 개수',
 'Max Gap': '최대 간격',
 'Max Overlap Ratio': '최대 겹침 비율',
 'Max copies by poster size': '포스터 크기별 최대 복사 수',
 'Maximum bend height of the side edges relative to the width': '폭 대비 옆 가장자리의 최대 휨 높이',
 'Maximum copies per source in this range, including first and manual placements. 0 excludes it from auto placement.': '이 구간에서 원본 하나당 최대 복사 수 (첫 배치와 수동 배치 '
                                                                                                                       '포함). 0이면 자동 배치에서 빠져요.',
 'Maximum length of fibers sticking out past the cut line.': '자른 선 밖으로 삐져나온 섬유의 최대 길이예요.',
 'Maximum overlap allowed, relative to the smaller poster area.': '더 작은 포스터 면적 대비 허용하는 최대 겹침.',
 'Medium': '중간',
 'Metallic': '금속성',
 'Min Lift Height (%)': '최소 들뜸 높이 (%)',
 'Min below 0 mixes both ways': '최소가 0보다 작으면 앞뒤가 섞여요',
 'Minimum Curl Angle': '최소 말림 각도',
 'Minimum Gap': '최소 간격',
 'Minimum Lift (%)': '최소 들뜸 (%)',
 'Minimum Tilt': '최소 기울기',
 'Minimum lift as a ratio of the poster height. Each poster lifts randomly between min and max. Set min negative and max positive to mix forward and backward bends.': '포스터 '
                                                                                                                                                                       '높이 '
                                                                                                                                                                       '대비 '
                                                                                                                                                                       '최소 '
                                                                                                                                                                       '들뜸. '
                                                                                                                                                                       '포스터마다 '
                                                                                                                                                                       '최소~최대 '
                                                                                                                                                                       '사이 '
                                                                                                                                                                       '랜덤. '
                                                                                                                                                                       '최소를 '
                                                                                                                                                                       '음수, '
                                                                                                                                                                       '최대를 '
                                                                                                                                                                       '양수로 '
                                                                                                                                                                       '하면 '
                                                                                                                                                                       '앞뒤 '
                                                                                                                                                                       '휨이 '
                                                                                                                                                                       '섞여요.',
 'Minus bends backward': '음수면 뒤로 휘어요',
 'Mix': '섞기',
 'Mix Types per Poster': '포스터마다 유형 섞기',
 'Mix both and one': '둘 다와 하나 섞기',
 'Mix both and one per poster': '포스터마다 둘 다와 하나 섞기',
 'Mix per poster': '포스터마다 섞기',
 'Mix which poster lands where': '어떤 포스터가 어디 갈지 섞기',
 'Model them flat (XY), +Z away from the wall,': '평평하게(XY) 모델링하고, +Z는 벽 바깥,',
 'More Options': '더 많은 옵션',
 'Move  ·  keep holding and press S size / R rotate  ·  %s': '이동  ·  누른 채로 S 크기 / R 회전  ·  {0}',
 'Move to Cut List': '자르기 목록으로 옮기기',
 'Move to Texture Images': '텍스처 이미지로 옮기기',
 'Moved %d selected · spacing %d px': '선택한 {0}장을 옮겼어요 · 간격 {1} px',
 'Moved %d to the cut list.': '자르기 목록으로 {0}장 옮겼어요.',
 'Moves all papers along the rail. Keyframe it to make them travel': '모든 종이를 레일 따라 옮겨요. 키프레임을 넣으면 움직여요',
 'Moves the checked texture images (or the highlighted row) to the cut list.': '체크한 텍스처 이미지(또는 강조된 줄)를 자르기 목록으로 옮겨요.',
 'Moves the current image to the texture list without cutting.': '지금 이미지를 자르지 않고 텍스처 목록으로 옮겨요.',
 'Name': '이름',
 'Name of the batch: the next one (before Build) or the one being edited (renamed right away).': '배치 이름: 다음 배치(만들기 전) 또는 편집 중인 배치(바로 이름이 바뀜).',
 'Name of the next batch collection (empty: Batch N · groups). Click it in the editor to change it': '다음 배치 컬렉션 이름 (비우면 배치 N · 그룹). 편집기에서 클릭해 바꿀 수 있어요',
 'Natural': '자연스럽게',
 'Natural spread at random spots': '랜덤 위치에 자연스럽게',
 'Natural: share of posters held with tape; the rest use the other kinds (pins...). Big posters lean a bit more to pins': '자연스럽게: 테이프로 붙일 포스터 비율. 나머지는 다른 '
                                                                                                                          '종류(핀...)를 써요. 큰 포스터는 핀을 조금 더 써요',
 'Neon Flyer': '형광 전단지',
 'Newer on Top': '새것이 위',
 'Next Texture Number': '다음 텍스처 번호',
 'No Effects': '효과 없음',
 'No Group': '그룹 없음',
 'No Lift': '들뜸 없음',
 'No Lift (flat)': '들뜸 없음 (평평)',
 'No baked textures in the folder.': '폴더에 구운 텍스처가 없어요.',
 'No boxes to remove.': '지울 상자가 없어요.',
 'No boxes to save · drag a box or use Find Cells by Green, or press Cancel.': "저장할 상자가 없어요 · 상자를 그리거나 '초록으로 칸 찾기'를 쓰거나 취소를 누르세요.",
 'No edges were selected, so all edges are used': '선택한 변이 없어서 모든 변을 써요',
 'No effects on the selected posters': '선택한 포스터에 효과가 없어요',
 'No faces to scatter on.': '뿌릴 면이 없어요.',
 'No flat posters. Excluded: ': '평평한 포스터가 없어요. 제외됨:',
 'No flat posters. Excluded: %s': '평평한 포스터가 없어요. 제외됨: {0}',
 'No fonts found': '글꼴을 찾지 못했어요',
 'No free space left around the other images': '다른 이미지 주변에 남은 빈 공간이 없어요',
 'No green (chroma-key) background found.': '초록(크로마키) 배경을 찾지 못했어요.',
 'No images are checked. Check the images to use in the list.': '체크된 이미지가 없어요. 목록에서 사용할 이미지를 체크하세요.',
 'No look on the selected posters': '선택한 포스터에 룩이 없어요',
 'No mesh posters in it': '안에 메시 포스터가 없어요',
 'No non-green artwork inside the cells.': '칸 안에 초록이 아닌 그림이 없어요.',
 'No normal output. Check the graph output names.': 'normal 출력이 없어요. 그래프 출력 이름을 확인하세요.',
 'No paper texture': '종이 질감 없음',
 'No poster material found.': '포스터 재질을 찾지 못했어요.',
 'No poster there. Click a poster, or Esc.': '거기엔 포스터가 없어요. 포스터를 클릭하거나 Esc.',
 'No scatter result on ': '스캐터 결과가 없어요:',
 'No scatter result on %s': '스캐터 결과가 없어요: {0}',
 'No tape / object where the paper is lifted off what is under it (curled corners, bent bottoms): it would not stick there': '종이가 아래에서 들뜬 곳(말린 모서리, 휜 아랫부분)에는 '
                                                                                                                             '테이프 / 오브젝트를 안 붙여요: 거기엔 붙지 않으니까요',
 'No usable texture found in the paper texture folder.': '종이 질감 폴더에서 쓸 수 있는 텍스처를 찾지 못했어요.',
 'Noise': '노이즈',
 'None': '없음',
 'Normal': '노멀',
 'Not all current posters fit on the %s canvas · remove a few or reduce their size.': '지금 포스터가 {0} 캔버스에 다 들어가지 않아요 · 몇 장 빼거나 크기를 줄여 주세요.',
 'Not available on curved areas yet': '곡면 영역에서는 아직 안 돼요',
 'Not enough free space for the %d selected · make room, select more, or press A then Pack for everything': '선택한 {0}장이 들어갈 빈 공간이 부족해요 · 공간을 비우거나 더 선택하거나, A를 '
                                                                                                            '누른 뒤 Pack으로 전체를 배치하세요',
 'Not enough room for everything, could not re-pack · reduce sizes or remove a few images.': '공간이 부족해서 다시 배치하지 못했어요 · 크기를 줄이거나 이미지를 몇 장 빼 주세요.',
 'Not enough room; new images overlap · reduce sizes or remove a few.': '공간이 부족해서 새 이미지가 겹쳐요 · 크기를 줄이거나 몇 장 빼 주세요.',
 'Not enough space to gather at the given spacing. Reduce the spacing or the image size.': '이 간격으로 모을 공간이 부족해요. 간격이나 이미지 크기를 줄여 주세요.',
 'Not placed yet': '아직 안 붙임',
 'Nothing checked · check the images to remove': '체크한 게 없어요 · 뺄 이미지를 체크하세요',
 'Nothing left to undo.': '더 되돌릴 게 없어요.',
 'Nothing painted; paint mode ended.': '칠한 게 없어서 칠하기 모드를 끝냈어요.',
 'Nothing to convert on ': '변환할 게 없어요:',
 'Nothing to convert on %s': '변환할 게 없어요: {0}',
 'Nothing visible there (transparent) · click on the image or a color cell': '거기엔 보이는 게 없어요(투명) · 이미지나 색 칸을 클릭하세요',
 'Numbered %d images by position (#%s) · Ctrl+Z to undo.': '이미지 {0}장에 위치 순서로 번호를 매겼어요 (#{1}) · Ctrl+Z로 되돌리기.',
 'Object that held the faces picked when the area was created': '영역을 만들 때 고른 면이 있던 오브젝트',
 'Off': '끄기',
 'Old Poster': '오래된 포스터',
 'Old Print': '오래된 인쇄',
 'Older on Top': '예전 것이 위',
 'Older setting, moved into the X Y Z rotation automatically': '이전 설정이라 X Y Z 회전으로 자동으로 옮겨졌어요',
 "On each poster's pivot (origin), e.g. a tape at the top center": '포스터마다 피벗(원점)에, 예: 위 가운데 테이프',
 'On: turns with the poster rotation (pick the axes with X Y Z). Off: stays upright': '켜면 포스터 회전을 따라 돌아요 (X Y Z로 축 선택). 끄면 똑바로 서 있어요',
 'One': '하나',
 'One Type per Poster': '포스터마다 한 가지 유형',
 'Only batches made with [Layout Editor · Build] can be re-edited.': '[레이아웃 편집기 · 만들기]로 만든 배치만 다시 편집할 수 있어요.',
 'Only one corner per poster': '포스터마다 모서리 하나만',
 'Only the left or right side per poster': '포스터마다 왼쪽 또는 오른쪽만',
 'Only where the layers below have no posters': '아래 레이어에 포스터가 없는 곳에만',
 'Opens the selected image large to adjust cut boxes. Applying saves individual PNGs and adds them to the list.': '선택한 이미지를 크게 열어 자르기 상자를 조절해요. 적용하면 각각 PNG로 '
                                                                                                                  '저장되고 목록에 추가돼요.',
 'Optimal': '최적',
 'Optimal for %d selected: ×%.2f · %d turned · others stay put · Ctrl+Z to undo': '선택한 {0}장 최적 배치: ×{1} · {2}장 회전 · 나머지는 그대로 · Ctrl+Z로 되돌리기',
 'Optimal layout: ×%.2f scale · %d rotated · usage %d%% → %d%% · Ctrl+Z to undo': '최적 배치: ×{0} 크기 · {1}장 회전 · 사용률 {2}% → {3}% · Ctrl+Z로 되돌리기',
 'Orange': '주황',
 'Original': '원본',
 'Original image color': '원본 이미지 색',
 'Other posters kept in place': '다른 포스터는 제자리 유지',
 'Output': '출력',
 'Output Resolution': '출력 해상도',
 'Over the layers below': '아래 레이어 위에',
 'Overlap': '겹침',
 'Overlap Depth Gap': '겹침 깊이 간격',
 'Overlap Grid': '겹친 격자',
 'Overlap: papers rest on each other': '겹침: 종이끼리 얹기',
 'Overlaps an unselected image. Please move in another direction.': '선택하지 않은 이미지와 겹쳐요. 다른 방향으로 옮겨 주세요.',
 'Pack': '채우기',
 'Pack Textures into .blend': '텍스처를 .blend에 포함',
 'Packed %d selected into the free space · others stay put%s · Ctrl+Z to undo': '선택한 {0}장을 빈 공간에 채웠어요 · 나머지는 그대로{1} · Ctrl+Z로 되돌리기',
 'Paint': '칠하기',
 'Paint Area': '영역 칠하기',
 'Paint Detail': '칠하기 세밀도',
 'Paint Where Posters Go': '포스터 붙일 곳 칠하기',
 'Paint mode ended.': '칠하기 모드를 끝냈어요.',
 'Paint off on %d poster%s · Ctrl+Z to undo': '포스터 {0}장 칠하기 끔 · Ctrl+Z로 되돌리기',
 'Paint tool off': '칠하기 도구 끔',
 'Paint · %s — drag over a poster  |  [ ] brush size  |  right-click to stop': '칠하기 · {0} — 포스터 위를 드래그  |  [ ] 브러시 크기  |  오른쪽 클릭으로 끝내기',
 'Paint: where posters may go': '칠하기: 포스터가 갈 수 있는 곳',
 'Palette %d': '팔레트 {0}',
 'Palette Random': '팔레트 랜덤',
 'Palettes hold up to 6 colors.': '팔레트에는 색이 6개까지 들어가요.',
 'Paper': '종이',
 'Paper Color Preset': '종이 색 프리셋',
 'Paper Color Strength': '종이 색 강도',
 'Paper Crumple': '종이 구김',
 'Paper Crumple · ': '종이 구김 ·',
 'Paper Crumple · %s': '종이 구김 · {0}',
 'Paper Lift': '종이 들뜸',
 'Paper Lift & Bend': '종이 들뜸 & 휨',
 'Paper Lift: curl the edges': '종이 들뜸: 가장자리 말기',
 'Paper Roughness': '종이 거칠기',
 'Paper Stiffness': '종이 뻣뻣함',
 'Paper Surface': '종이 표면',
 'Paper Texture': '종이 질감',
 'Paper bends along the surface and sticks completely (e.g. flyers on a pole)': '종이가 표면을 따라 휘어 완전히 붙어요 (예: 기둥의 전단지)',
 'Paper color': '종이 색',
 'Paper color (light areas)': '종이 색 (밝은 부분)',
 'Paper color (white areas)': '종이 색 (흰 부분)',
 'Paper crumple is removed by pressing the checked [Paper Crumple] button again': '종이 구김은 체크된 [종이 구김] 버튼을 한 번 더 누르면 빠져요',
 'Paper lifted more than this off the wall / paper below counts as lifted': '벽 / 아래 종이에서 이보다 더 떨어진 종이는 들뜬 것으로 봐요',
 'Paper sizes for posters and notes': '포스터와 메모용 종이 크기',
 'Paper stays flat and touches the curved surface. It is lifted over concave spots so it never intersects': '종이는 평평하게 유지하고 곡면에 닿아요. 오목한 곳에서는 들려서 절대 파고들지 않아요',
 'Paper taped only at the top: the bottom lifts and the sides bend outward': '위쪽만 테이프로 붙인 종이: 아래가 들리고 옆이 바깥으로 휘어요',
 'Paper texture applied: %d materials, %d meshes got coords': '종이 질감 적용: 재질 {0}개, 메시 {1}개에 좌표 추가',
 'Paper texture removed: %d materials': '종이 질감 제거: 재질 {0}개',
 'Papers covered by other papers are pressed against the wall, removing lift and tilt, so upper papers never float. (Includes other scatter areas stacked on top)': '다른 '
                                                                                                                                                                    '종이에 '
                                                                                                                                                                    '덮인 '
                                                                                                                                                                    '종이를 '
                                                                                                                                                                    '벽에 '
                                                                                                                                                                    '눌러 '
                                                                                                                                                                    '들뜸과 '
                                                                                                                                                                    '기울기를 '
                                                                                                                                                                    '없애서, '
                                                                                                                                                                    '위 '
                                                                                                                                                                    '종이가 '
                                                                                                                                                                    '뜨지 '
                                                                                                                                                                    '않아요. '
                                                                                                                                                                    '(위에 '
                                                                                                                                                                    '쌓은 '
                                                                                                                                                                    '다른 '
                                                                                                                                                                    '스캐터 '
                                                                                                                                                                    '영역 '
                                                                                                                                                                    '포함)',
 'Papers hang square to the rail, following its slope and curves': '레일의 기울기와 굽이를 따라 종이가 레일에 수직으로 걸려요',
 'Papers hang straight down whatever the rail angle': '레일 각도와 상관없이 종이가 똑바로 아래로 걸려요',
 'Papers sliding past the end come back at the start (closed rails always wrap)': '끝을 지나간 종이가 시작에서 다시 나와요 (닫힌 레일은 항상 돌아와요)',
 'Paste (empty)': '붙여넣기 (비어 있음)',
 'Paste Effects to #%d': '#{0}에 효과 붙여넣기',
 'Pasted effects to %d images from #%d': '#{1}의 효과를 이미지 {0}장에 붙여넣었어요',
 'Pastel Print': '파스텔 인쇄',
 'Pattern #': '무늬 #',
 'Pattern Size': '무늬 크기',
 'Pattern Size (mm)': '무늬 크기 (mm)',
 'Pattern Size mm': '무늬 크기 mm',
 'Peel': '벗기기',
 'Peel Print': '인쇄 벗기기',
 'Peel · Holes': '벗겨짐 · 구멍',
 'Peels off only the print, revealing white paper. No holes.': '인쇄면만 벗겨서 흰 종이가 드러나요. 구멍은 생기지 않아요.',
 'Pen': '펜',
 'Per Poster': '포스터당',
 'Per-Poster Variation': '포스터마다 다르게',
 'Photo Finish': '사진 마감',
 'Photo Order': '사진 순서',
 'Photo Roughness': '사진 거칠기',
 'Photo Strip': '포토 스트립',
 'Photo Strips': '포토 스트립',
 'Photo paper is not metal: keep 0 for a real print. Raise only for foil / metallic paper looks': '인화지는 금속이 아니에요: 실제 인화는 0으로 두세요. 호일 / 메탈릭 종이 느낌일 때만 올리세요',
 'Photo prints and instant films: card size, white border and film look': '사진 인화와 인스턴트 필름: 카드 크기, 흰 테두리, 필름 룩',
 'Photo strip %d×%d on a %s card (%.0f×%.0f mm) from %d photo(s)%s · originals unchecked in the list': '{2} 카드({3}×{4} mm)에 사진 {5}장으로 {0}×{1} 포토 스트립을 만들었어요{6} '
                                                                                                       '· 원본은 목록에서 체크 해제',
 'Photos are mixed along the rail · change Random Seed for another mix': '레일을 따라 사진이 섞여요 · 다른 조합은 랜덤 시드를 바꾸세요',
 'Photos hang in their atlas number order (1, 2, 3...) · renumber them in the Atlas layout with W': '아틀라스 번호 순서(1, 2, 3...)대로 걸어요 · 아틀라스 레이아웃에서 W로 번호를 바꿀 수 '
                                                                                                    '있어요',
 'Pick': '고르기',
 'Pick Color': '색 고르기',
 'Pick Color Manually': '색 직접 고르기',
 'Pick a collection first': '먼저 컬렉션을 고르세요',
 'Pick a collection or one object.': '컬렉션이나 오브젝트 하나를 고르세요.',
 'Pick a curve or a mesh with edges': '커브나 변이 있는 메시를 고르세요',
 'Pick a look first (greyed out until then)': '먼저 룩을 고르세요 (그 전엔 비활성)',
 'Pick a mesh as the rail first.': '먼저 레일로 쓸 메시를 고르세요.',
 'Pick a poster collection below': '아래에서 포스터 컬렉션을 고르세요',
 'Pick a poster collection, then press Reload.': '포스터 컬렉션을 고른 뒤 다시 불러오기를 누르세요.',
 'Pick a tool and drag over a poster. Paint shows as a preview and is committed only with [Apply] below. [Cancel] discards it.': '도구를 고르고 포스터 위를 드래그하세요. 칠한 건 '
                                                                                                                                 '미리보기로 보이고, 아래 [적용]을 눌러야 '
                                                                                                                                 '확정돼요. [취소]는 버려요.',
 'Pick an effect first (greyed out until then)': '먼저 효과를 고르세요 (그 전엔 비활성)',
 'Pick an effect first, then Off removes it': '효과를 먼저 고른 뒤 끄기를 누르면 빠져요',
 'Pick another scatter area on the same wall. Its posters (and every layer under it) are taken into account: fill the empty space around them, or lie on top of them': '같은 '
                                                                                                                                                                       '벽의 '
                                                                                                                                                                       '다른 '
                                                                                                                                                                       '스캐터 '
                                                                                                                                                                       '영역을 '
                                                                                                                                                                       '고르세요. '
                                                                                                                                                                       '그 '
                                                                                                                                                                       '포스터(와 '
                                                                                                                                                                       '그 '
                                                                                                                                                                       '아래 '
                                                                                                                                                                       '모든 '
                                                                                                                                                                       '레이어)를 '
                                                                                                                                                                       '고려해서 '
                                                                                                                                                                       '주변 '
                                                                                                                                                                       '빈 '
                                                                                                                                                                       '곳을 '
                                                                                                                                                                       '채우거나 '
                                                                                                                                                                       '그 '
                                                                                                                                                                       '위에 '
                                                                                                                                                                       '얹어요',
 'Pick any font installed on this computer for the text (type to search)': '이 컴퓨터에 설치된 글꼴 중 하나를 골라요 (입력해서 검색)',
 'Pick at random from a collection of tapes / objects': '테이프 / 오브젝트 컬렉션에서 랜덤으로 골라요',
 'Pick one from the list or type a new name.': '목록에서 고르거나 새 이름을 입력하세요.',
 'Picture': '사진',
 'Picture Settings': '사진 설정',
 'Picture removed from %d image(s) · back to their own size': '이미지 {0}장에서 사진 설정을 뺐어요 · 원래 크기로 돌아가요',
 'Pink': '분홍',
 'Pinned posters count too': '고정한 포스터도 포함돼요',
 'Pivot': '피벗',
 'Place': '붙이기',
 'Place Again': '다시 붙이기',
 'Place Angle': '붙일 각도',
 'Place Poster': '포스터 붙이기',
 'Place Scale': '붙일 크기',
 'Place Specific Posters': '원하는 포스터 붙이기',
 'Place Without Lift': '들뜸 없이 붙이기',
 'Place it inside the area. Also check overlaps with other manually placed posters.': '영역 안에 붙이세요. 직접 붙인 다른 포스터와 겹치는지도 확인하세요.',
 'Place only this poster flat, without lift or bend': '이 포스터만 들뜨거나 휘지 않고 평평하게 붙여요',
 'Place posters only where the layers below have none, so nothing covers them': '아래 레이어에 포스터가 없는 곳에만 붙여서 아무것도 가리지 않아요',
 'Place: pin a chosen poster': '붙이기: 고른 포스터 고정',
 'Placed %d poster%s on %s. Adjust them in the panel.': '{2}에 포스터 {0}장을 붙였어요. 패널에서 조절하세요.',
 'Placement error: ': '배치 오류:',
 'Placement error: %s': '배치 오류: {0}',
 'Please add images to cut in the [Images to Cut] tab first.': '먼저 [자를 이미지] 탭에 자를 이미지를 추가해 주세요.',
 'Please add images.': '이미지를 추가해 주세요.',
 'Please check images to use or select all images.': '사용할 이미지를 체크하거나 전체를 선택해 주세요.',
 'Please choose a collection that contains mesh posters.': '메시 포스터가 들어 있는 컬렉션을 골라 주세요.',
 'Please choose a folder for cut PNGs under Image Cutting.': '이미지 자르기에서 잘라낸 PNG를 저장할 폴더를 골라 주세요.',
 'Please choose a folder to save textures.': '텍스처를 저장할 폴더를 골라 주세요.',
 'Please choose a poster from the poster collection to place.': '포스터 컬렉션에서 붙일 포스터를 골라 주세요.',
 'Please close the open cut editor first.': '열려 있는 자르기 편집기를 먼저 닫아 주세요.',
 'Please close the open editor first.': '열려 있는 편집기를 먼저 닫아 주세요.',
 'Please move images inside the canvas.': '이미지를 캔버스 안으로 옮겨 주세요.',
 'Please select a wall or floor.': '벽이나 바닥을 선택해 주세요.',
 'Please select mesh faces of a wall or floor.': '벽이나 바닥의 메시 면을 선택해 주세요.',
 'Please select posters.': '포스터를 선택해 주세요.',
 'Please select the faces to scatter on.': '포스터를 뿌릴 면을 선택해 주세요.',
 'Polaroid': '폴라로이드',
 'Portion of the short side that folds at the corner': '모서리에서 접히는 짧은 변의 비율',
 'Portion of the width that bends from the side': '옆에서 휘는 폭의 비율',
 'Poster Library': '포스터 라이브러리',
 'Poster Material · ': '포스터 재질 ·',
 'Poster Pin can then use "Group · Name" for all of them.': '그러면 Poster Pin에서 "그룹 · 이름"으로 한꺼번에 쓸 수 있어요.',
 'Poster Print: add to list': 'Poster Print: 목록에 추가',
 'Poster collection for the new layer. Use a separate batch per paper kind so each keeps its own crumple, gloss and lighting': '새 레이어의 포스터 컬렉션. 종이 종류마다 배치를 따로 '
                                                                                                                               '쓰면 구김·광택·조명이 각자 유지돼요',
 'Poster cutting: Drag corners·edges = Resize / Drag inside = Move / Wheel = Zoom / Middle button = Pan / Enter = Apply / Esc = Cancel': '포스터 자르기: 모서리·변 드래그 = '
                                                                                                                                         '크기 / 안쪽 드래그 = 이동 / 휠 '
                                                                                                                                         '= 확대 / 가운데 버튼 = 이동 / '
                                                                                                                                         'Enter = 적용 / Esc = '
                                                                                                                                         '취소',
 'Poster size': '포스터 크기',
 'Poster to Place': '붙일 포스터',
 'Posters: the collection to use': '포스터: 쓸 컬렉션',
 'Prefixed to texture file, object and collection names. Only letters, digits and _ are used; if empty, Poster is used.': '텍스처 파일, 오브젝트, 컬렉션 이름 앞에 붙어요. '
                                                                                                                          '영문·숫자·_만 써요. 비우면 Poster를 써요.',
 'Preset holes·peeling·wear (torn bill etc.) will not appear where painted. Use it to protect text.': '칠한 곳에는 프리셋 구멍·벗겨짐·마모(찢긴 전단지 등)가 생기지 않아요. 글자를 지킬 때 쓰세요.',
 'Press Flat When Covered': '덮이면 평평하게 누르기',
 'Press OK to switch to this color.': '확인을 누르면 이 색으로 바뀌어요.',
 'Press Reload Collection Sources.': "'컬렉션 원본 다시 불러오기'를 누르세요.",
 'Press Strength': '누르는 힘',
 'Preview': '미리보기',
 'Previewing: %s · %d posters': '미리보기: {0} · 포스터 {1}장',
 'Previous Effects': '이전 효과',
 'Print & Pin, part 1: cut image sheets, age the paper, frame photos and print them as poster textures with exact UVs.': 'Print & Pin 1부: 이미지 시트를 자르고, 종이를 낡게 '
                                                                                                                         '하고, 사진 테두리를 씌워 정확한 UV의 포스터 텍스처로 '
                                                                                                                         '출력합니다.',
 'Print & Pin, part 2: pin posters onto walls and strings in layers, with tape, pins and clips': 'Print & Pin 2부: 포스터를 벽과 끈에 여러 겹으로 붙여요. 테이프, 핀, 집게도 함께',
 'Print 4×6': '인화 4×6',
 'Print 5×7': '인화 5×7',
 'Print Peel': '인쇄 벗겨짐',
 'Print Surface': '인화면',
 'Protect': '보호',
 'Purple': '보라',
 'Put every Tape & Objects setting back to default. The chosen collection / object is kept': '테이프 & 오브젝트 설정을 모두 기본값으로 되돌려요. 고른 컬렉션 / 오브젝트는 그대로예요',
 'Puts all images in the list on one sheet. Count and rows/columns are recalculated as images are added or removed.': '목록의 모든 이미지를 한 장에 넣어요. 이미지를 넣거나 빼면 개수와 '
                                                                                                                      '행/열이 다시 계산돼요.',
 'Quick Guide': '빠른 안내',
 'R rotate · S scale · +/- 10% · Esc': 'R 회전 · S 크기 · +/- 10% · Esc',
 'Rail': '레일',
 'Rail Line · ': '레일 선 ·',
 'Rail made. Pick a poster collection in the panel to hang posters.': '레일을 만들었어요. 패널에서 포스터 컬렉션을 고르면 포스터가 걸려요.',
 'Rail uses %d edge%s': '레일이 변 {0}개를 써요',
 'Rail uses all edges': '레일이 모든 변을 써요',
 'Rail · ': '레일 ·',
 'Rail · %s': '레일 · {0}',
 'Rail: papers hang flat from the line': '레일: 종이가 선에서 평평하게 걸려요',
 'Random': '랜덤',
 'Random Lift per Poster': '포스터마다 랜덤 들뜸',
 'Random Scale': '랜덤 크기',
 'Random Scale ±': '랜덤 크기 ±',
 'Random Seed': '랜덤 시드',
 'Random Size': '랜덤 크기',
 'Random Size  →': '랜덤 크기  →',
 'Random Size (±%)': '랜덤 크기 (±%)',
 'Random Size cancelled': '랜덤 크기 취소',
 'Random Size ±%d%%': '랜덤 크기 ±{0}%',
 'Random Size · 0% · nothing changed': '랜덤 크기 · 0% · 바뀐 게 없어요',
 'Random Size · drag right to raise ±%, release to apply · Esc cancels': '랜덤 크기 · 오른쪽으로 드래그하면 ±%가 커져요, 놓으면 적용 · Esc 취소',
 'Random Size: each selected image gets its own size within ± this percent of its current size, keeping its ratio': '랜덤 크기: 선택한 이미지마다 지금 크기의 ± 이 퍼센트 안에서 비율을 '
                                                                                                                    '유지한 채 크기가 정해져요',
 'Random Turn': '랜덤 회전',
 'Random corners: chance for each corner to get one': '랜덤 모서리: 모서리마다 붙을 확률',
 'Random rotation around the clip point': '집게 지점을 중심으로 랜덤 회전',
 'Random spots along the top edge': '윗변을 따라 랜덤 위치',
 'Random spots anywhere on the paper': '종이 아무 곳에나 랜덤 위치',
 'Random stacking order': '랜덤 쌓기 순서',
 'Random tilt between min and max for each poster (reshuffle with the lift seed)': '포스터마다 최소~최대 사이에서 랜덤 기울기 (들뜸 시드로 다시 섞기)',
 'Random turn of each paper around its own up axis (world Z on a wall), so one side comes off the surface. The low side stays on the surface': '종이마다 자기 위쪽 '
                                                                                                                                               '축(벽에서는 월드 Z)으로 '
                                                                                                                                               '랜덤하게 돌려서 한쪽이 '
                                                                                                                                               '표면에서 떨어져요. 낮은 '
                                                                                                                                               '쪽은 표면에 붙어 있어요',
 'Random up/down variation of each paper': '종이마다 위아래 랜덤 변화',
 'Random variation of the spacing': '간격의 랜덤 변화',
 'Random ±': '랜덤 ±',
 'Random ±%d%%  ·  release': '랜덤 ±{0}%  ·  놓으면 적용',
 'Re-edit': '다시 편집',
 'Re-edit Built Posters': '만든 포스터 다시 편집',
 'Re-packed %d images without changing size · %d turned 90° inside the texture only · Ctrl+Z to undo': '크기는 그대로 두고 이미지 {0}장을 다시 배치했어요 · {1}장은 텍스처 안에서만 90° '
                                                                                                       '돌렸어요 · Ctrl+Z로 되돌리기',
 'Re-packed %d images without changing size · Ctrl+Z to undo': '크기는 그대로 두고 이미지 {0}장을 다시 배치했어요 · Ctrl+Z로 되돌리기',
 'Re-packed everything to fit the new images · Ctrl+Z to undo.': '새 이미지에 맞게 전체를 다시 배치했어요 · Ctrl+Z로 되돌리기.',
 'Re-rolls hole and tear positions for each image.': '이미지마다 구멍과 찢김 위치를 다시 정해요.',
 'Re-split into %d cols × %d rows = %d · Ctrl+Z to undo.': '{0}열 × {1}행 = {2}칸으로 다시 나눴어요 · Ctrl+Z로 되돌리기.',
 'Re-spread Other Posters': '다른 포스터 다시 펼치기',
 'Real-world size one hole-pattern tile covers. Smaller means finer, more numerous holes.': '구멍 무늬 타일 하나가 덮는 실제 크기예요. 작을수록 더 잘고 많은 구멍이 생겨요.',
 'Real-world size one texture tile covers. Wrinkles look the same size regardless of poster size.': '질감 타일 하나가 덮는 실제 크기예요. 포스터 크기와 상관없이 주름 크기가 같아 보여요.',
 'Recalculate the scatter with the current settings (stays editable)': '지금 설정으로 스캐터를 다시 계산해요 (계속 고칠 수 있어요)',
 'Red': '빨강',
 'Red Marker': '빨간 마커',
 'Regular': '보통',
 'Reload': '다시 불러오기',
 'Remove': '빼기',
 'Remove Box  (Del)': '상자 지우기  (Del)',
 'Remove Box %d  (Del)': '상자 {0} 지우기  (Del)',
 'Remove Built Images from List': '만든 이미지는 목록에서 빼기',
 'Remove Checked Images': '체크한 이미지 빼기',
 'Remove Color': '색 빼기',
 'Remove Current Item': '현재 항목 빼기',
 'Remove Image from List': '목록에서 이미지 빼기',
 'Remove Manual Placement': '직접 배치 빼기',
 'Remove Shadows': '그림자 지우기',
 'Remove Shadows off': '그림자 지우기 끔',
 'Remove Shadows on · gray or dark-green shadows touching the green background are removed too (Trim / Find / save)': '그림자 지우기 켬 · 초록 배경에 닿은 회색·짙은 초록 그림자도 '
                                                                                                                      '지워져요 (잘라 맞추기 / 찾기 / 저장)',
 'Removed %d from the layout (%s) · Ctrl+Z to undo.': '레이아웃에서 {0}장을 뺐어요 ({1}) · Ctrl+Z로 되돌리기.',
 'Removed %d image%s from the list · source files kept · Ctrl+Z to undo': '목록에서 이미지 {0}장을 뺐어요 · 원본 파일은 그대로 · Ctrl+Z로 되돌리기',
 'Removed %s.': '{0} 뺐어요.',
 'Removed box %d · %d left · Ctrl+Z to undo': '상자 {0}을 지웠어요 · {1}개 남음 · Ctrl+Z로 되돌리기',
 'Removed one effect layer from %d selected.': '선택한 {0}장에서 효과 한 겹을 뺐어요.',
 'Removes a manually placed poster': '직접 붙인 포스터를 빼요',
 'Removes it only from the cut list. Source files are kept.': '자르기 목록에서만 빼요. 원본 파일은 그대로예요.',
 'Removes the checked images from the list (nothing checked: the highlighted one). Source files are not deleted. Ctrl+Z brings them back.': '체크한 이미지를 목록에서 빼요 '
                                                                                                                                            '(없으면 강조된 것). 원본 '
                                                                                                                                            '파일은 지워지지 않고, '
                                                                                                                                            'Ctrl+Z로 되돌릴 수 '
                                                                                                                                            '있어요.',
 'Removes the checked images from the list. Nothing checked: the highlighted one. Source files are kept.': '체크한 이미지를 목록에서 빼요. 체크가 없으면 강조된 것. 원본 파일은 그대로예요.',
 'Rename "%s"': '"{0}" 이름 바꾸기',
 'Rename Group': '그룹 이름 바꾸기',
 'Rename…': '이름 바꾸기…',
 'Reopened %s · %d images. [Build] will update this batch.': '{0} 다시 열기 · 이미지 {1}장. [만들기]를 누르면 이 배치가 업데이트돼요.',
 'Reopens an existing poster batch in the layout editor. Adjust color, wear, holes, crumple or size and [Build] to update the same posters, including ones placed on walls.': '기존 '
                                                                                                                                                                              '포스터 '
                                                                                                                                                                              '배치를 '
                                                                                                                                                                              '레이아웃 '
                                                                                                                                                                              '편집기에서 '
                                                                                                                                                                              '다시 '
                                                                                                                                                                              '열어요. '
                                                                                                                                                                              '색, '
                                                                                                                                                                              '마모, '
                                                                                                                                                                              '구멍, '
                                                                                                                                                                              '구김, '
                                                                                                                                                                              '크기를 '
                                                                                                                                                                              '고친 '
                                                                                                                                                                              '뒤 '
                                                                                                                                                                              '[만들기]를 '
                                                                                                                                                                              '누르면 '
                                                                                                                                                                              '벽에 '
                                                                                                                                                                              '붙인 '
                                                                                                                                                                              '것까지 '
                                                                                                                                                                              '같은 '
                                                                                                                                                                              '포스터가 '
                                                                                                                                                                              '업데이트돼요.',
 'Reorder or clear the image list.': '이미지 목록 순서 바꾸기 또는 비우기.',
 'Repeats as far as count and space allow': '개수와 공간이 허락하는 만큼 반복해요',
 'Replaces dark areas with this color.': '어두운 부분을 이 색으로 바꿔요.',
 'Requires a build result and the Poster Scatter addon.': '만든 결과와 Poster Scatter 애드온이 필요해요.',
 'Reset': '초기화',
 'Reset Seed': '시드 초기화',
 'Reset Settings': '설정 초기화',
 'Reset Tape & Objects': '테이프 & 오브젝트 초기화',
 'Reset effects on %d poster%s · Ctrl+Z to undo': '포스터 {0}장 효과 초기화 · Ctrl+Z로 되돌리기',
 'Reset size': '크기 초기화',
 'Reshuffle': '다시 섞기',
 'Reshuffle Patterns': '무늬 다시 섞기',
 'Rest on Papers Below': '아래 종이에 얹기',
 'Restored %d removed images.': '뺐던 이미지 {0}장을 되돌렸어요.',
 'Reuse': '반복',
 'Reuse Posters': '포스터 반복 사용',
 'Reuse off: stops when all are used': '반복 끔: 다 쓰면 멈춰요',
 'Reverse Direction': '방향 반대로',
 'Right 90°  (E)': '오른쪽 90°  (E)',
 'Riso Print': '리소 인쇄',
 'Rotate %.0f°  ·  Ctrl 15° steps  ·  S size  ·  %s  ·  Esc cancel': '회전 {0}°  ·  Ctrl 15° 단위  ·  S 크기  ·  {1}  ·  Esc 취소',
 'Rotate Image': '이미지 회전',
 'Rotate Image 90°': '이미지 90° 회전',
 'Rotate papers around the world X axis. On a wall: tilts papers forward or back': '월드 X축으로 종이를 돌려요. 벽에서는 앞뒤로 기울어져요',
 'Rotate papers around the world Y axis. On a wall: spins papers flat on the wall': '월드 Y축으로 종이를 돌려요. 벽에서는 벽 위에서 빙글 돌아요',
 'Rotate papers around the world Z axis. On a wall: turns papers around the vertical axis': '월드 Z축으로 종이를 돌려요. 벽에서는 세로축을 중심으로 돌아요',
 'Rotate: move mouse left/right · Shift fine · Ctrl 15° steps · Click/R/Enter confirm · Esc revert': '회전: 마우스 좌우 · Shift 세밀 · Ctrl 15° 단위 · 클릭/R/Enter 확정 · '
                                                                                                     'Esc 되돌리기',
 'Rotates the current preview image. The source file is kept; the rotation is used when building textures and posters.': '지금 미리보기 이미지를 돌려요. 원본 파일은 그대로고, 텍스처와 '
                                                                                                                         '포스터를 만들 때 회전이 적용돼요.',
 'Rotation Range (old)': '회전 범위 (이전)',
 'Rotation: X Y Z on, then Random': '회전: X Y Z를 켜고 랜덤',
 'Roughness': '거칠기',
 'Row/column count exceeds the source image size.': '행/열 개수가 원본 이미지 크기를 넘어요.',
 'Rows': '행',
 'Rows down each paper so it can follow an up-down curve (domes, arches). 1 = no extra cuts': '위아래로 휜 곡면(돔, 아치)을 따라가도록 종이를 세로로 나누는 행 수. 1 = 추가로 안 나눔',
 'Rows: how many even pieces each paper is cut into from top to bottom. Bends use these lines. The source is unchanged': '행: 종이를 위에서 아래로 몇 조각으로 나눌지. 이 선을 따라 '
                                                                                                                         '휘어요. 원본은 그대로예요',
 'SD Folder': 'SD 폴더',
 'Same name in another batch = the same group:': '다른 배치에서 같은 이름 = 같은 그룹:',
 'Satin': '새틴',
 'Saturation': '채도',
 'Saturation %d': '채도 {0}',
 'Save %d Cut PNGs': '잘라낸 PNG {0}장 저장',
 'Save Folder': '저장 폴더',
 'Saved %d PNGs and added them to the [Texture Images] list': 'PNG {0}장을 저장하고 [텍스처 이미지] 목록에 추가했어요',
 'Saves empty PNG areas as transparent.': 'PNG의 빈 부분을 투명으로 저장해요.',
 'Saves external PNGs and also packs the image data. Save the .blend yourself.': 'PNG를 외부에 저장하고 이미지 데이터도 포함해요. .blend 저장은 직접 하세요.',
 'Saves into per-cut subfolders inside this folder. If empty, the texture folder is used.': '잘라낼 때마다 이 폴더 안의 하위 폴더에 저장해요. 비우면 텍스처 폴더를 써요.',
 'Scale': '크기 조절',
 'Scale %d%%': '크기 {0}%',
 'Scale %d%%  ·  move left / right  ·  Ctrl 5%% steps  ·  click or Enter to apply  ·  Esc cancel': '크기 {0}%  ·  좌우로 움직이기  ·  Ctrl 5% 단위  ·  클릭 또는 Enter로 적용  '
                                                                                                   '·  Esc 취소',
 'Scale %s with mouse': '마우스로 {0} 크기 조절',
 'Scale cancelled': '크기 조절 취소',
 'Scale factor for the poster to place. You can also change it with S or +/- while placing.': '붙일 포스터의 크기 배율. 붙이는 중 S나 +/-로도 바꿀 수 있어요.',
 'Scale factor for this poster only (overall scale × this value)': '이 포스터만의 크기 배율 (전체 크기 × 이 값)',
 'Scale to fit inside the entered size': '입력한 크기 안에 맞게 크기 조절',
 'Scale with mouse': '마우스로 크기 조절',
 'Scale · 100% · nothing changed': '크기 · 100% · 바뀐 게 없어요',
 'Scale · apply the entered size as is': '크기 조절 · 입력한 크기를 그대로 적용',
 'Scales while keeping the original ratio of the whole photo.': '사진 전체의 원래 비율을 유지한 채 크기를 조절해요.',
 'Scatter Along Curve': '커브 따라 뿌리기',
 'Scatter Along Edges': '변 따라 뿌리기',
 'Scatter Along Rail': '레일 따라 뿌리기',
 'Scatter Posters': '포스터 뿌리기',
 'Scatter made. Pick a poster collection in the panel to place posters.': '스캐터를 만들었어요. 패널에서 포스터 컬렉션을 고르면 포스터가 붙어요.',
 'Scatter naturally at random positions.': '랜덤 위치에 자연스럽게 뿌려요.',
 'Scatter on Selected Faces': '선택한 면에 뿌리기',
 'Scatter on This Wall': '이 벽에 뿌리기',
 'Scatter settings were reset to defaults.': '스캐터 설정을 기본값으로 초기화했어요.',
 'Scene Undo is paused while the Layout Editor is open · close the editor first (Ctrl+Z over the editor undoes layout steps)': '레이아웃 편집기가 열려 있는 동안 씬 되돌리기가 멈춰요 '
                                                                                                                               '· 먼저 편집기를 닫으세요 (편집기 위에서 '
                                                                                                                               'Ctrl+Z는 레이아웃 단계를 되돌려요)',
 'Seed': '시드',
 'Select': '선택',
 'Select (or deselect) every name in the list. Selection is for Group; checkboxes are not changed': '목록의 모든 이름을 선택(또는 해제)해요. 선택은 그룹용이고 체크박스는 바뀌지 않아요',
 'Select 2 images to swap their numbers · or 3+ to number them by position (top row first, left to right).': '이미지 2장을 고르면 번호를 서로 바꾸고, 3장 이상이면 위치 순서(윗줄부터 '
                                                                                                             '왼쪽→오른쪽)로 번호를 매겨요.',
 'Select All Images (Ctrl+A)': '이미지 전체 선택 (Ctrl+A)',
 'Select All Names': '이름 전체 선택',
 'Select Images to Build': '만들 이미지 고르기',
 'Select a curve, or edges of a mesh.': '커브, 또는 메시의 변을 선택하세요.',
 'Select a scatter area or its result': '스캐터 영역이나 그 결과를 선택하세요',
 'Select a scatter first.': '먼저 스캐터를 선택하세요.',
 'Select an image first': '이미지를 먼저 선택하세요',
 'Select an image first, then press Add Text': '이미지를 먼저 선택한 뒤 글자 추가를 누르세요',
 'Select at least two strings (curves or lines) to hang along all of them.': '모두 따라 걸려면 끈(커브나 선)을 두 개 이상 선택하세요.',
 'Select images first · A selects all': '먼저 이미지를 선택하세요 · A = 전체 선택',
 'Select images to apply effects to first.': '효과를 적용할 이미지를 먼저 선택하세요.',
 'Select images to apply effects to. Press A to select all.': '효과를 적용할 이미지를 선택하세요. A를 누르면 전체 선택이에요.',
 'Select images to move. Press A to select all.': '옮길 이미지를 선택하세요. A를 누르면 전체 선택이에요.',
 'Select images to remove first.': '먼저 뺄 이미지를 선택하세요.',
 'Select posters first · A selects all': '먼저 포스터를 선택하세요 · A = 전체 선택',
 'Select posters of one group to rename it': '이름을 바꿀 그룹의 포스터를 선택하세요',
 'Select the edges to hang the posters from.': '포스터를 걸 변을 선택하세요.',
 'Select the photos for the strip first · A selects all': '먼저 스트립에 넣을 사진을 선택하세요 · A = 전체 선택',
 'Select the posters to color first · A selects all': '먼저 색을 입힐 포스터를 선택하세요 · A = 전체 선택',
 'Selected #%d  |  %d × %d px  |  You can also save with Enter.': '#{0} 선택  |  {1} × {2} px  |  Enter로도 저장할 수 있어요.',
 'Selected Image Size': '선택한 이미지 크기',
 'Selected Only': '선택한 것만',
 'Selected Posters': '선택한 포스터',
 'Selected faces of ': '선택한 면:',
 'Selected faces of %s': '{0}의 선택한 면',
 'Set Paper Color of Selected Posters': '선택한 포스터 종이 색 지정',
 'Set Rows/Columns': '행/열 지정',
 'Sets color, wear, holes and tears for the images selected in the layout editor. Baked into the texture on build.': '레이아웃 편집기에서 선택한 이미지의 색, 마모, 구멍, 찢김을 정해요. '
                                                                                                                     '만들 때 텍스처에 구워져요.',
 'Share of posters that get one. 1 = all of them': '하나씩 받을 포스터 비율. 1 = 전부',
 'Shift + stroke: soft blend': 'Shift + 칠하기: 부드럽게 섞기',
 'Shift every other row by half a cell to hide the grid look': '격자 느낌이 안 나게 한 줄 건너 반 칸씩 밀어요',
 'Show Colors': '색 보기',
 'Show Placed Posters': '붙인 포스터 보기',
 'Show Posters': '포스터 보기',
 'Show Scatter Area Bounds': '스캐터 영역 경계 보기',
 'Show Source Posters': '원본 포스터 보기',
 'Showing: ': '보는 중:',
 'Showing: %s': '보는 중: {0}',
 'Shows or hides the placed posters of every scatter in the viewport (renders are not affected)': '모든 스캐터의 붙인 포스터를 뷰포트에서 보이거나 숨겨요 (렌더에는 영향 없음)',
 'Shows or hides the scatter area bounds (wire boxes) on poles and walls in the viewport. They never appear in renders.': '기둥과 벽의 스캐터 영역 경계(와이어 상자)를 뷰포트에서 '
                                                                                                                          '보이거나 숨겨요. 렌더에는 절대 안 나와요.',
 'Shows the original poster gallery after it has been scattered. Off hides it in the viewport and in renders; placed posters are not affected.': '뿌린 뒤 원본 포스터 '
                                                                                                                                                 '갤러리를 보여줘요. '
                                                                                                                                                 '끄면 뷰포트와 렌더에서 '
                                                                                                                                                 '숨겨요; 붙인 포스터는 '
                                                                                                                                                 '영향 없어요.',
 'Shuffle': '섞기',
 'Side': '옆',
 'Side Bend (%)': '옆 휨 (%)',
 'Side Lift Width': '옆 들뜸 폭',
 'Sides (mm)': '옆 (mm)',
 'Silk': '실크',
 'Single Color': '단색',
 'Size': '크기',
 'Size %d%%  ·  Ctrl 5%% steps': '크기 {0}%  ·  Ctrl 5% 단위',
 'Size %d%%  ·  move left / right  ·  Ctrl 5%% steps  ·  R rotate  ·  %s  ·  Esc cancel': '크기 {0}%  ·  좌우로 움직이기  ·  Ctrl 5% 단위  ·  R 회전  ·  {1}  ·  Esc 취소',
 'Size Scale': '크기 배율',
 'Size data differs from the layout size. Select the images and press the size again.': '크기 데이터가 레이아웃 크기와 달라요. 이미지를 선택하고 크기를 다시 눌러 주세요.',
 'Size data does not match the image count.': '크기 데이터가 이미지 개수와 맞지 않아요.',
 'Size of every placed poster compared with its source': '원본과 비교한 모든 포스터의 크기',
 'Size of the objects (1 = as modeled)': '오브젝트 크기 (1 = 모델 그대로)',
 'Skip Lifted Spots': '들뜬 곳 건너뛰기',
 'Sky Blue': '하늘색',
 'Slide': '밀기',
 'Small': '작게',
 'Small gap so the objects do not flicker with the paper': '오브젝트가 종이와 깜빡이며 겹쳐 보이지 않게 조금 띄워요',
 'Small values give crisp knife-cut edges; large values bleed softly like clouds.': '작으면 칼로 자른 듯 또렷하고, 크면 구름처럼 부드럽게 번져요.',
 'Smallest curl angle (°) when Vary per Poster is on': '포스터마다 다르게를 켰을 때 가장 작은 말림 각도(°)',
 'Smallest space kept between posters when they may not overlap': '겹치면 안 될 때 포스터 사이에 남기는 가장 작은 공간',
 'Smoothness (paper divisions)': '매끄러움 (종이 분할)',
 'Snap  ·  B off  ·  Shift straight': '스냅  ·  B 끄기  ·  Shift 직선',
 'Snap (while B is held) · edges and corners stick to other images at the Spacing distance': "스냅 (B를 누르는 동안) · 변과 모서리가 '간격' 거리에서 다른 이미지에 붙어요",
 'Soft': '부드럽게',
 'Source': '원본',
 'Source Face Object': '원본 면 오브젝트',
 'Source image missing: ': '원본 이미지가 없어요:',
 'Source image missing: %s': '원본 이미지가 없어요: {0}',
 'Source sheets with several images on one page': '한 장에 여러 그림이 있는 원본 시트',
 'Sources': '원본',
 'Spacing  %d px': '간격  {0} px',
 'Spacing (px)': '간격 (px)',
 'Spacing Between Images': '이미지 사이 간격',
 'Spacing Jitter': '간격 흐트러짐',
 'Spacing between images (px)': '이미지 사이 간격 (px)',
 'Spacing of the paintable grid on new areas. Smaller paints finer but is heavier': '새 영역의 칠할 수 있는 격자 간격. 작을수록 세밀하지만 무거워요',
 'Split Grid Image': '격자 이미지 나누기',
 'Split by Count': '개수로 나누기',
 'Splits a combined image into equal cells.': '합쳐진 이미지를 같은 크기 칸으로 나눠요.',
 'Spray': '스프레이',
 'Spread large posters over the whole area and fit small posters into the remaining gaps. Keeps source sizes.': '큰 포스터를 영역 전체에 펼치고 작은 포스터를 남은 틈에 끼워요. 원본 크기를 '
                                                                                                                '유지해요.',
 'Square texture size in pixels': '정사각형 텍스처 크기 (픽셀)',
 'Square texture · posters keep their size': '정사각형 텍스처 · 포스터 크기는 그대로',
 'Square to Rail': '레일에 수직',
 'Stack on Lower Scatter': '아래 레이어 위에 쌓기',
 'Stack on Top': '위에 쌓기',
 'Stacking': '쌓는 순서',
 'Stagger': '엇갈리게',
 'Stagger Columns': '열 엇갈리게',
 'Stamp·Seal': '도장·인장',
 'Start from the other end of the rail': '레일의 반대쪽 끝에서 시작해요',
 'Starting angle for the next pinned poster (R while placing rotates it)': '다음에 붙일 포스터의 시작 각도 (붙이는 중 R로 회전)',
 'Stick your own tape, pins or other objects onto every poster': '모든 포스터에 직접 만든 테이프, 핀 등 오브젝트를 붙여요',
 'Sticky Note': '스티키 노트',
 'Sticky Note 4 Colors': '스티키 노트 4색',
 'Sticky Note Lift': '스티키 노트 들뜸',
 'Sticky Note Random Color': '스티키 노트 랜덤 색',
 'Sticky note color added (%d/6) · change it with [Change Color].': '스티키 노트 색을 추가했어요 ({0}/6) · [색 바꾸기]로 바꿀 수 있어요.',
 'Sticky note lift: glue strip 20 %, lift 5-24 %.': '스티키 노트 들뜸: 접착 부분 20 %, 들뜸 5-24 %.',
 'Stop Editing This Batch': '이 배치 편집 그만하기',
 'Straight Cut': '직선 자르기',
 'Straight Down': '똑바로 아래로',
 'Street Flyer': '길거리 전단지',
 'Strength': '강도',
 'Strength Scale': '강도 배율',
 'Strip Columns': '스트립 열',
 'Strip Frame': '스트립 테두리',
 'Strip Rows': '스트립 행',
 'Strong': '강하게',
 'Substance Designer Folder': 'Substance Designer 폴더',
 'Sun Faded': '햇빛 바램',
 'Surface': '표면',
 'Surface %.2f': '표면 {0}',
 'Surface Offset': '표면 띄우기',
 'Surface · %s': '표면 · {0}',
 'Surface: %s · %d image(s)': '표면: {0} · 이미지 {1}장',
 'Swapped numbers #%d and #%d · Ctrl+Z to undo.': '#{0}와 #{1} 번호를 바꿨어요 · Ctrl+Z로 되돌리기.',
 'Swing': '흔들림',
 'Tape & Objects': '테이프 & 오브젝트',
 'Tape & Objects settings were reset.': '테이프 & 오브젝트 설정을 초기화했어요.',
 'Tape / Object': '테이프 / 오브젝트',
 'Tape / Object Collection': '테이프 / 오브젝트 컬렉션',
 'Tape Position': '테이프 위치',
 'Tape Share': '테이프 비율',
 'Tape Width': '테이프 폭',
 'Taped': '테이프',
 'Tear': '찢김',
 'Tear Adjust': '찢김 조정',
 'Tear Depth (mm)': '찢김 깊이 (mm)',
 'Tear Depth mm': '찢김 깊이 mm',
 'Tear Holes': '구멍 내기',
 'Tears the paper to make holes. Torn edges show a white paper cross-section.': '종이를 찢어 구멍을 내요. 찢긴 가장자리에 흰 종이 단면이 보여요.',
 'Text': '글자',
 'Text deleted · Ctrl+Z to undo': '글자를 지웠어요 · Ctrl+Z로 되돌리기',
 'Texture Images': '텍스처 이미지',
 'Texture Layout': '텍스처 레이아웃',
 'Texture Layout · %d · %d × %d': '텍스처 레이아웃 · {0} · {1} × {2}',
 'Texture Size': '텍스처 크기',
 'Texture Size (px)': '텍스처 크기 (px)',
 'Texture layout: Space + Left drag or Middle drag = Pan / Wheel = Zoom / Home = Frame all / Ctrl Z = Undo / Enter = Build / Esc = Close editor': '텍스처 레이아웃: '
                                                                                                                                                  'Space + 왼쪽 '
                                                                                                                                                  '드래그 또는 가운데 '
                                                                                                                                                  '드래그 = 이동 / '
                                                                                                                                                  '휠 = 확대 / '
                                                                                                                                                  'Home = 전체 '
                                                                                                                                                  '보기 / Ctrl Z '
                                                                                                                                                  '= 되돌리기 / '
                                                                                                                                                  'Enter = 만들기 '
                                                                                                                                                  '/ Esc = 편집기 '
                                                                                                                                                  '닫기',
 'Textures': '텍스처',
 'That size is larger than the canvas. Please increase the output resolution.': '캔버스보다 큰 크기예요. 출력 해상도를 올려 주세요.',
 'The bottom edge lifts': '아래 가장자리가 들려요',
 'The collection holding your posters: flat planes in their local XY, +Y up (Poster Atlas makes these)': '포스터가 들어 있는 컬렉션: 로컬 XY의 평평한 면, +Y가 위 (Poster Atlas가 '
                                                                                                         '이렇게 만들어요)',
 'The cut region is outside the image bounds.': '자를 영역이 이미지 밖에 있어요.',
 'The image list is out of sync with the layout · try again.': '이미지 목록이 레이아웃과 맞지 않아요 · 다시 시도해 주세요.',
 'The left or right side lifts (random per poster)': '왼쪽 또는 오른쪽이 들려요 (포스터마다 랜덤)',
 'The next Build makes a new batch instead of updating the one being edited': '다음 만들기는 편집 중인 배치를 업데이트하지 않고 새 배치를 만들어요',
 'The one object put on every poster. Origin = where it touches / grips the paper': '모든 포스터에 붙일 오브젝트 하나. 원점 = 종이에 닿는 / 집는 곳',
 'The poster to pin by clicking on the wall': '벽을 클릭해서 붙일 포스터',
 'The rail has no edges to hang from.': '레일에 종이를 걸 변이 없어요.',
 'The rail is vertical or too short to hang papers from.': '레일이 세로이거나 너무 짧아서 종이를 걸 수 없어요.',
 'The resolution changed. Please reopen the layout editor.': '해상도가 바뀌었어요. 레이아웃 편집기를 다시 열어 주세요.',
 'The selected image has no paint.': '선택한 이미지에 칠한 게 없어요.',
 "The selected images don't fit in the free space · make room or select fewer": '선택한 이미지가 빈 공간에 들어가지 않아요 · 공간을 비우거나 더 적게 선택하세요',
 'The selected images have no Picture settings.': '선택한 이미지에 사진 설정이 없어요.',
 'The trim margin is larger than the cell size.': '잘라낼 여백이 칸 크기보다 커요.',
 'The turned block is too big for the texture · turn fewer images, or reduce sizes.': '돌린 묶음이 텍스처보다 커요 · 더 적게 돌리거나 크기를 줄여 주세요.',
 'The white border of instant film and prints is a little less shiny than the picture': '인스턴트 필름과 인화지의 흰 테두리는 사진보다 조금 덜 반짝여요',
 'The width/height ratio of the whole photo changes.': '사진 전체의 가로·세로 비율이 바뀌어요.',
 'There is no previous build batch to update.': '업데이트할 이전 빌드 배치가 없어요.',
 'This layout always overlaps': '이 레이아웃은 항상 겹쳐요',
 'Tick the box to curl paper edges': '체크하면 종이 가장자리가 말려요',
 'Tick to use posters more than once': '체크하면 포스터를 여러 번 써요',
 'Tight overlapping board (sticky notes)': '빽빽하게 겹친 보드 (스티키 노트)',
 'Tile Size mm': '타일 크기 mm',
 'Tilt from Pivot': '피벗에서 기울이기',
 'Tilts the bottom away from the wall around the source pivot.': '원본 피벗을 중심으로 아랫부분을 벽에서 띄워요.',
 'Tint': '틴트',
 'Tints only the white paper areas with this color.': '흰 종이 부분만 이 색으로 물들여요.',
 'Tip: one batch per paper kind keeps its own look': '팁: 종이 종류마다 배치 하나씩이면 각자 느낌이 유지돼요',
 'Toggle Preview': '미리보기 전환',
 'Too many cells for a %s card.': '{0} 카드에 넣기엔 칸이 너무 많아요.',
 'Too many divisions for the image size.': '이미지 크기에 비해 분할이 너무 많아요.',
 'Too many images or the ratio is too long. Please use fewer images at once.': '이미지가 너무 많거나 비율이 너무 길어요. 한 번에 더 적은 이미지를 써 주세요.',
 'Too many rows/columns.': '행/열이 너무 많아요.',
 'Tools': '도구',
 'Top': '위',
 'Top (mm)': '위 (mm)',
 'Top Center': '위 가운데',
 'Top Corners': '위 모서리',
 'Top Two': '위 두 곳',
 'Torn Bill': '찢긴 전단지',
 'Torn Edges': '찢긴 가장자리',
 'Torn Layer (white cross-section)': '찢긴 층 (흰 단면)',
 'Transparent': '투명',
 'Trim Green to Fit': '초록 잘라 맞추기',
 'Trimmed green from %d cells': '칸 {0}개에서 초록을 잘라냈어요',
 'Turn (Z)': '돌리기 (Z)',
 'Turn on X, Y or Z (world axes)': 'X, Y, Z를 켜세요 (월드 축)',
 'Turn the placed posters into a real mesh (final, no longer editable by the addon). The scatter setup is kept hidden as a backup unless Keep Backup is off': '붙인 '
                                                                                                                                                              '포스터를 '
                                                                                                                                                              '실제 '
                                                                                                                                                              '메시로 '
                                                                                                                                                              '바꿔요 '
                                                                                                                                                              '(최종, '
                                                                                                                                                              '애드온으로 '
                                                                                                                                                              '더 '
                                                                                                                                                              '고칠 '
                                                                                                                                                              '수 '
                                                                                                                                                              '없어요). '
                                                                                                                                                              "'백업 "
                                                                                                                                                              "유지'를 "
                                                                                                                                                              '끄지 '
                                                                                                                                                              '않으면 '
                                                                                                                                                              '스캐터 '
                                                                                                                                                              '설정은 '
                                                                                                                                                              '숨겨서 '
                                                                                                                                                              '백업으로 '
                                                                                                                                                              '남겨요',
 'Turn with Poster': '포스터와 함께 돌리기',
 'Turned %d images as one block %s 90°': '이미지 {0}장을 한 묶음으로 {1} 90° 돌렸어요',
 'Turned off %s': '{0} 껐어요',
 'Turned off paper crumple': '종이 구김을 껐어요',
 'Turned off the effect being chosen': '고르던 효과를 껐어요',
 'Type  ·  drag the box to move  ·  Alt+Enter new line  ·  Alt ↑↓ line spacing  ·  Enter done (then S size · R rotate)': '입력 중  ·  상자를 드래그해 이동  ·  Alt+Enter '
                                                                                                                         '줄바꿈  ·  Alt ↑↓ 줄 간격  ·  Enter 완료 '
                                                                                                                         '(그다음 S 크기 · R 회전)',
 'Typewriter': '타자기',
 'Undo Paint': '칠하기 되돌리기',
 'Undone (%d steps left)': '되돌렸어요 ({0}단계 남음)',
 'Up': '위로',
 'Up to %d faces per paper': '종이당 면 최대 {0}개',
 'Up to 12 ranges can be set.': '구간은 12개까지 정할 수 있어요.',
 'Update': '업데이트',
 'Update Previous Build Batch': '이전 빌드 배치 업데이트',
 'Update Scatter': '스캐터 업데이트',
 'Use': '사용',
 'Use Click Wall to Place from the 3D View sidebar.': "3D 뷰 사이드바에서 '벽 클릭해서 붙이기'를 쓰세요.",
 'Use Selected Edges': '선택한 변 쓰기',
 'Use each poster more than once, to fill large areas': '넓은 곳을 채우려고 포스터를 여러 번 써요',
 'Use it from the 3D View.': '3D 뷰에서 쓰세요.',
 'Use one object you choose (e.g. a clothespin)': '고른 오브젝트 하나만 써요 (예: 빨래집게)',
 'Use the edges selected on the rail mesh (in Edit Mode) as the rail. With Clear, every edge is used again': '레일 메시에서 (편집 모드로) 선택한 변을 레일로 써요. 지우기를 하면 다시 모든 변을 '
                                                                                                             '써요',
 'Using all edges': '모든 변 사용',
 'Variant': '변형',
 'Variant Count': '변형 개수',
 'Varies fade and yellowing per poster.': '포스터마다 바램과 누렇게 변함을 다르게 해요.',
 'Vary per Poster': '포스터마다 다르게',
 'Vary per sheet': '장마다 다르게',
 'Vertical': '세로',
 'Vertical Divisions': '세로 분할',
 'WIDTH (X)': '가로 (X)',
 'Wall / floor': '벽 / 바닥',
 'Warm': '따뜻하게',
 'Warm Film': '따뜻한 필름',
 'Watercolor Paper': '수채화 종이',
 'Weaker with Depth': '깊을수록 약하게',
 'Wear': '마모',
 'Wear Adjust': '마모 조정',
 'Wear Random': '마모 랜덤',
 'Wears the corners more.': '모서리를 더 닳게 해요.',
 'Wheel zoom · ← → previous·next · Q left 90° / E right 90° · Home frame all': '휠 확대 · ← → 이전·다음 · Q 왼쪽 90° / E 오른쪽 90° · Home 전체 보기',
 'When off, papers return to flat. Pivot tilt is separate.': '끄면 종이가 평평해져요. 피벗 기울이기는 따로예요.',
 'When on, each poster randomly uses one (sometimes two) of the chosen types. When off, all chosen types apply together': '켜면 포스터마다 고른 유형 중 하나(가끔 둘)를 랜덤하게 써요. '
                                                                                                                          '끄면 고른 유형이 모두 함께 적용돼요',
 'When on, newly placed posters stick flat without lift or bend': '켜면 새로 붙인 포스터가 들뜨거나 휘지 않고 평평하게 붙어요',
 'When on, the max count matches the number of posters provided (× repeats when repeat is on).': '켜면 최대 개수가 준비된 포스터 수와 같아져요 (반복을 켜면 × 반복 수).',
 'When placed, the other posters re-arrange around it': '붙이면 다른 포스터가 그 주변으로 다시 배치돼요',
 'Where': '위치',
 'Where posters go': '포스터 붙일 곳',
 'Where the paper starts to bend, top 0 to bottom 1. Everything above stays flat on the wall (for a sticky note: its glue strip)': '종이가 휘기 시작하는 위치, 위 0 ~ 아래 '
                                                                                                                                   '1. 그 위는 벽에 평평하게 붙어 있어요 '
                                                                                                                                   '(스티키 노트라면 접착 부분)',
 'Which edges lift': '어느 가장자리가 들뜰지',
 'Which panel sections are open. Kept per scene so Collapse All can switch them together.': "패널 섹션별 열림 상태. 씬마다 저장돼서 '모두 접기'로 한꺼번에 바꿀 수 있어요.",
 'White': '흰색',
 'White = posters · black = none': '흰색 = 포스터 · 검은색 = 없음',
 'White Border': '흰 테두리',
 'White Cross-section': '흰 단면',
 'White Cross-section Width mm': '흰 단면 폭 mm',
 'White Rim': '흰 테두리',
 'White background': '흰 배경',
 'White border': '흰 테두리',
 'White paper fibers exposed inside the worn edge.': '닳은 가장자리 안쪽에 드러난 흰 종이 섬유예요.',
 'Wide areas where the print layer peeled off, exposing white paper. Holes always form inside these areas.': '인쇄층이 벗겨져 흰 종이가 드러난 넓은 부분이에요. 구멍은 항상 이 안에 생겨요.',
 'Width': '가로',
 'Width (mm)': '가로 (mm)',
 'Width and height must be greater than 0.': '가로와 세로는 0보다 커야 해요.',
 'Width of the white paper band exposed around holes.': '구멍 둘레에 드러난 흰 종이 띠의 폭이에요.',
 'Width the tape holds, relative to the poster width': '테이프가 잡는 폭 (포스터 폭 대비)',
 'With Posters Below': '아래 포스터와의 관계',
 'Worn Edges': '닳은 가장자리',
 'Wrap Around': '돌아오기',
 'Write': '쓰기',
 'Write a handwritten caption on the bottom margin of the selected photo cards (instant formats). Empty text removes it': '선택한 사진 카드(인스턴트 형식)의 아래 여백에 손글씨 문구를 '
                                                                                                                          '써요. 비우면 지워져요',
 'X Angle': 'X 각도',
 'Y Angle': 'Y 각도',
 'Yellow': '노랑',
 'Yellowing': '누렇게 변함',
 'Yellowing of old paper.': '오래된 종이가 누렇게 변한 정도예요.',
 'You can also choose it in the [Paper] tab of the [Layout Editor · Build] window.': '[레이아웃 편집기 · 만들기] 창의 [종이] 탭에서도 고를 수 있어요.',
 'You cannot remove all of them. Keep at least one.': '전부 뺄 수는 없어요. 하나는 남겨 주세요.',
 'Z Angle': 'Z 각도',
 'click to apply': '클릭하면 적용',
 'fills the gaps below': '아래 빈 곳 채움',
 'in the empty space': '빈 곳에',
 'ink color': '잉크 색',
 'lies on the layers below': '아래 레이어 위에 얹음',
 'no group': '그룹 없음',
 'on top': '위에',
 'origin where they touch the paper.': '원점은 종이에 닿는 곳.',
 'paper color': '종이 색',
 'release to apply': '놓으면 적용',
 'sbscooker not found.': 'sbscooker를 찾을 수 없어요.',
 'sbsrender not found. Please set the Substance Designer folder.': 'sbsrender를 찾을 수 없어요. Substance Designer 폴더를 지정해 주세요.',
 'sticky note color': '스티키 노트 색',
 '… %d more groups': '… 그룹 {0}개 더',
 '− Remove': '− 빼기',
 '포스터 묶음': '포스터 묶음',
 '포스트잇': '포스트잇'}


MASK='배치_영역'; GROUP='배치_크기'; SEED='배치_시드'
NODE='Poster Scatter · Collection Instance'
BUSY=False; SIGNATURES={}; PLACERS=[]; PENDING={}; LAST_COST={}; SOURCE_SETS={}
PICKS={}   # Per area: footprint, height and origin (auto / manual) of every placed poster, for click-to-grab
_SUPPRESS=[False]   # True while several manual values are set at once (one rebuild at the end)

def make_node():
    g=bpy.data.node_groups.get(NODE)
    if g:return g
    g=bpy.data.node_groups.new(NODE,'GeometryNodeTree');g.use_fake_user=True
    for name,direction,kind in [('Scatter Points','INPUT','NodeSocketGeometry'),('Poster Collection','INPUT','NodeSocketCollection'),('Posters','OUTPUT','NodeSocketGeometry')]:
        g.interface.new_socket(name=name,in_out=direction,socket_type=kind)
    def node(kind,name,x,y):
        n=g.nodes.new(kind);n.label=name;n.location=(x,y);return n
    a=node('NodeGroupInput','Computed scatter points',-620,200)
    c=node('GeometryNodeCollectionInfo','Normalized poster sources',-620,-80)
    c.inputs['Separate Children'].default_value=True;c.inputs['Reset Children'].default_value=True
    idx=node('GeometryNodeInputNamedAttribute','Poster Index',-380,-260);idx.data_type='INT';idx.inputs['Name'].default_value='poster_index'
    rot=node('GeometryNodeInputNamedAttribute','Rotation',-380,-430);rot.data_type='FLOAT_VECTOR';rot.inputs['Name'].default_value='poster_rotation'
    scale=node('GeometryNodeInputNamedAttribute','Scale Factor',-380,-610);scale.data_type='FLOAT';scale.inputs['Name'].default_value='poster_scale'
    inst=node('GeometryNodeInstanceOnPoints','Poster Instances',0,180);inst.inputs['Pick Instance'].default_value=True
    out=node('NodeGroupOutput','Scatter Result',280,180)
    for src,output,dst,input in [(a,'Scatter Points',inst,'Points'),(a,'Poster Collection',c,'Collection'),(c,'Instances',inst,'Instance'),(idx,'Attribute',inst,'Instance Index'),(rot,'Attribute',inst,'Rotation'),(scale,'Attribute',inst,'Scale'),(inst,'Instances',out,'Posters')]:g.links.new(src.outputs[output],dst.inputs[input])
    return g

def sources(collection):
    return sorted([o for o in collection.all_objects if o.type=='MESH' and not o.get('ps_owned')],key=lambda o:o.name) if collection else []

def source_signature(collection):
    items=[]
    for o in sources(collection):
        uv=o.data.uv_layers.active
        items.append((o.get('poster_id',o.name),[tuple(v.co) for v in o.data.vertices],
                      [tuple(v.uv) for v in uv.data] if uv else [],
                      [o.matrix_world.to_3x3().col[i].length for i in range(3)],
                      [m.name if m else '' for m in o.data.materials]))
    return hashlib.sha256(repr(sorted(items,key=lambda v:v[0])).encode()).hexdigest()

_SIG_CACHE={}


def source_signature_cached(collection):
    """The panel redraws on every mouse move, so the source comparison runs at most once every 2 seconds."""
    if collection is None:return source_signature(collection)
    now=time.monotonic();hit=_SIG_CACHE.get(collection.name)
    if hit and now-hit[0]<2.:return hit[1]
    sig=source_signature(collection);_SIG_CACHE[collection.name]=(now,sig);return sig


def source_geometry(o,s):
    # Atlas posters use local XY, +Y is the top; location/rotation in the source gallery are ignored.
    mesh=bpy.data.meshes.new_from_object(o.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    if not mesh.vertices:
        bpy.data.meshes.remove(mesh);raise ValueError(o.name+' : empty mesh.')
    lengths=[o.matrix_world.to_3x3().col[i].length for i in range(3)]
    for v in mesh.vertices:v.co=Vector(tuple(v.co[i]*lengths[i] for i in range(3)))
    low=Vector([min(v.co[i] for v in mesh.vertices) for i in range(3)])
    high=Vector([max(v.co[i] for v in mesh.vertices) for i in range(3)])
    w,h=high.x-low.x,high.y-low.y
    if min(w,h)<1e-6 or high.z-low.z>max(w,h)*.05:
        bpy.data.meshes.remove(mesh);raise ValueError(o.name+' : a flat poster in the local XY plane is required.')
    # Cut flat source quads before bending: BMesh interpolates every UV layer.
    # One broad upper face; remaining faces cluster near the lower edge.
    for v in mesh.vertices:v.co.z-=(low.z+high.z)*.5
    conform=s.curved and s.surface_mode=='CONFORM' and s.layout!='RAIL'   # rail papers hang flat from the line
    tape=s.lift_enabled and False and s.attach_mode=='TAPE'
    if len(mesh.vertices)==4 and len(mesh.polygons)==1 and (s.bend_faces>1 or s.bend_faces_x>1 or s.curl_side or s.curl_corner or (conform and s.conform_faces+s.conform_faces_v>2) or tape):
        bm=bmesh.new();bm.from_mesh(mesh)
        def cut(co,no):
            bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
                dist=1e-8,plane_co=co,plane_no=no,clear_inner=False,clear_outer=False)
        if tape:   # Tape: tape line on top + even grid across width/height
            rows=max(s.bend_faces,2);cols=max(s.bend_faces_x,2);ya=high.y-h*TAPE_STRIP;tw=w*s.tape_width;cx=(low.x+high.x)/2
            cut((0,ya,0),(0,1,0))
            for i in range(1,rows):cut((0,ya-(ya-low.y)*i/rows,0),(0,1,0))
            for i in range(1,cols):cut((low.x+w*i/cols,0,0),(1,0,0))
            for xx in (cx-tw/2,cx+tw/2,low.x+tw,high.x-tw):
                if low.x<xx<high.x:cut((xx,0,0),(1,0,0))
        elif not conform:   # Flat walls and rails: an even grid, Vertical = rows, Horizontal = columns. Bends use these lines.
            for i in range(1,s.bend_faces):cut((0,low.y+h*i/s.bend_faces,0),(0,1,0))
            for i in range(1,s.bend_faces_x):cut((low.x+w*i/s.bend_faces_x,0,0),(1,0,0))
        else:
          for i in range(s.bend_faces-1):
            t=1-(1-i/(s.bend_faces-1))**2.0
            fraction=s.bend_start+(1-s.bend_start)*t
            cut((0,high.y-h*fraction,0),(0,1,0))
        m=max(s.bend_faces_x,2) if conform else 0   # Curved walls: side/corner fold segments
        for fold in curl_folds(s,low.x,high.x,low.y,high.y,[f for f in ('L','R','BL','BR') if not tape and ((f in 'LR' and s.curl_side) or (len(f)==2 and s.curl_corner))]):
            n,c,_=fold;band=fold[2]
            for i in range(m-1):
                t=1-(1-i/(m-1))**2.0;d=c+band*t
                cut((n[0]*d,n[1]*d,0),(n[0],n[1],0))
        if conform:
            for i in range(1,s.conform_faces):cut((low.x+w*i/s.conform_faces,0,0),(1,0,0))      # columns: follow a sideways curve
            for i in range(1,s.conform_faces_v):cut((0,low.y+h*i/s.conform_faces_v,0),(0,1,0))  # rows: follow an up-down curve
        bm.to_mesh(mesh);bm.free()
    base=mesh.attributes.new('ps_rest_position','FLOAT_VECTOR','POINT')
    base.data.foreach_set('vector',[v for p in mesh.vertices for v in p.co])
    return mesh,w,h

def topology_signature(s):
    return str((s.bend_faces,s.bend_faces_x,s.lift_enabled and False and s.attach_mode=='TAPE',round(s.tape_width,4),s.bend_start,2.0,s.curl_side,s.curl_corner,round(s.side_band,4),round(s.corner_size,4),
                s.curved and s.surface_mode=='CONFORM' and s.layout!='RAIL',(s.conform_faces,s.conform_faces_v) if s.curved and s.surface_mode=='CONFORM' and s.layout!='RAIL' else 'even-grid'))


def curl_folds(s,left,right,bottom,top,kinds):
    """Fold lines: (outward direction n, fold line position c, fold width). The part where n·p > c curls up."""
    w=right-left;h=top-bottom;out=[]
    for k in kinds:
        if k=='B':
            line=top-h*s.bend_start;out.append(((0.,-1.),-line,line-bottom))
        elif k=='L':
            b=w*s.side_band;out.append(((-1.,0.),-(left+b),b))
        elif k=='R':
            b=w*s.side_band;out.append(((1.,0.),right-b,b))
        else:   # Bottom corner: folds at 45° by the same length on both edges
            leg=min(w,h)*s.corner_size;r=math.sqrt(.5)
            n=(-r if k=='BL' else r,-r);cx=left if k=='BL' else right
            corner=cx*n[0]+bottom*n[1];band=leg*r
            out.append((n,corner-band,band))
    return out


def curl_kinds(s,obj,x,y,ordinal):
    """Which sides lift for each poster (always the same for the same layout and seed)."""
    types=[t for t,on in (('B',s.curl_bottom),('S',s.curl_side),('C',s.curl_corner)) if on]
    if not types:return ()
    key=('curl|%s|%.7f|%.7f|%d|%d'%(obj['source'],x,y,ordinal,s.lift_seed)).encode()
    rng=random.Random(int.from_bytes(hashlib.blake2b(key,digest_size=8).digest(),'big'))
    if s.curl_mix:
        pick=[rng.choice(types)]
        rest=[t for t in types if t not in pick]
        if rest and rng.random()<.3:pick.append(rng.choice(rest))   # Occasionally both together
    else:pick=types
    out=[]
    for t in ('B','S','C'):
        if t not in pick:continue
        side=rng.random()<.5
        both=s.side_pair=='BOTH' or (s.side_pair=='MIX' and rng.random()<.5)
        if t=='B':out.append('B')
        elif t=='S':out+=['L','R'] if both else ['L' if side else 'R']
        else:
            both=s.corner_pair=='BOTH' or (s.corner_pair=='MIX' and rng.random()<.5)
            out+=['BL','BR'] if both else ['BL' if side else 'BR']
    return tuple(out)


def apply_fold(coords,n,c,target,angle=None):
    ds=[co.x*n[0]+co.y*n[1]-c for co in coords]
    length=max(ds)
    if length<=1e-9:return coords
    if angle is not None:   # Specified as curl angle (can roll past 90° like a sticky note)
        if angle<=1e-4:return coords
        radius=length/angle
    else:
        if target<=1e-10:return coords
        # Circular arc, preserving the paper's length; the part behind the fold stays flat.
        target=min(target,length*2/math.pi)
        lo,hi=0.,math.pi/2
        for _ in range(32):
            mid=(lo+hi)/2
            if length*(1-math.cos(mid))/mid<target:lo=mid
            else:hi=mid
        radius=length/((lo+hi)/2)
    out=[]
    for co,d in zip(coords,ds):
        if d<=0:out.append(co);continue
        th=d/radius;delta=radius*math.sin(th)-d
        out.append(Vector((co.x+n[0]*delta,co.y+n[1]*delta,co.z+radius*(1-math.cos(th)))))
    return out


def shaped_fold(coords,n,c,target,p):
    """Like apply_fold, but the curve follows height = t^p along the bent part (paper length kept):
    p=1 a straight ramp from the fold line, p=2 an even curve, higher p = flat near the glue line and curling at the tip."""
    ds=[co.x*n[0]+co.y*n[1]-c for co in coords];length=max(ds)
    if length<=1e-9 or target<=1e-10:return coords
    prof=arc_profile(length,target,False,p)
    out=[]
    for co,d in zip(coords,ds):
        if d<=0:out.append(co);continue
        along,hgt=prof(d);along=float(along);hgt=float(hgt)
        out.append(Vector((co.x+n[0]*(along-d),co.y+n[1]*(along-d),co.z+hgt)))
    return out


TAPE_STRIP=.06   # Top band covered by tape (fraction of height)


def arc_profile(L,H,smooth=False,p=2.):
    """Paper of length L bending up to height H: distance d from the attached edge -> (distance along wall, height). Paper length is preserved."""
    t=np.linspace(0.,1.,257);H=min(max(H,0.),.9*L)
    if smooth:f=(1-np.cos(np.pi*t))/2;df=np.pi/2*np.sin(np.pi*t)
    else:p=max(p,1.);f=t**p;df=p*t**(p-1)
    def arc(U):
        g=np.sqrt(U*U+(H*df)**2);return np.concatenate([[0.],np.cumsum((g[1:]+g[:-1])/2*np.diff(t))])
    lo,hi=0.,L
    for _ in range(40):
        mid=(lo+hi)/2
        if arc(mid)[-1]<L:lo=mid
        else:hi=mid
    U=(lo+hi)/2;cum=arc(U)
    return lambda d:(np.interp(d,cum,t*U),np.interp(d,cum,H*f))


def tape_coordinates(rest,s,frac,kinds,position):
    """Paper taped only at the top: the bottom lifts and the sides bend outward."""
    xs=np.array([p.x for p in rest]);ys=np.array([p.y for p in rest]);zs=np.array([p.z for p in rest])
    left,right,bottom,top=xs.min(),xs.max(),ys.min(),ys.max();w=right-left;h=top-bottom
    strength=frac/max(s.bottom_lift_percent/100,1e-9)   # Random lift strength 0-1
    ya=top-h*TAPE_STRIP;U=max(ya-bottom,1e-9)
    u=np.clip(ya-ys,0,None);tb=u/U
    nx,ny=xs.copy(),ys.copy();lift=np.zeros_like(xs)
    if 'B' in kinds and frac>0:
        uf,zb=arc_profile(U,frac*h,False,s.tape_curve)(u);ny=np.where(u>0,ya-uf,ys);lift+=zb
    side=strength*w*s.tape_side/100
    if side>0 and position!='TOP_EDGE':
        if position=='TOP_CENTER':
            cx=(left+right)/2;half=w*s.tape_width/2;V=max(w/2-half,1e-9);prof=arc_profile(V,side,False,s.tape_curve)
            d=np.clip(np.abs(xs-cx)-half,0,None);vf,zx=prof(d);sign=np.sign(xs-cx)
            on=((sign<0)&('L' in kinds))|((sign>0)&('R' in kinds))
            nx=np.where(on&(d>0),cx+sign*(half+vf),nx);lift+=np.where(on,zx*(.35+.65*tb),0)
        elif 'L' in kinds and 'R' in kinds:   # Top two corners: the middle bulges out slightly
            tw=w*s.tape_width;V=max(w-2*tw,1e-9);t=np.clip((xs-left-tw)/V,0,1)
            lift+=min(side,.1*w)*np.sin(np.pi*t)*tb
    return [Vector((float(a),float(b),float(c+l))) for a,b,c,l in zip(nx,ny,zs,lift)]


def tape_position_for(s,obj,x,y,ordinal):
    if s.tape_position!='RANDOM':return s.tape_position
    key=('tape|%s|%.7f|%.7f|%d|%d'%(obj['source'],x,y,ordinal,s.lift_seed)).encode()
    return ('TOP_CENTER','TOP_CENTER','TOP_CORNERS','TOP_EDGE')[hashlib.blake2b(key,digest_size=1).digest()[0]%4]


def rest_on_surface(coords,rest):
    """Back-bent paper lying on a surface: tilt it (around both in-plane axes) so it rests on its
    lowest supports under its center, e.g. the curled edge and the opposite edge both touch,
    instead of floating flat above the curl. Height is set afterwards by the placement."""
    if len(coords)<3:return coords
    P=np.array([tuple(c) for c in coords],np.float64)
    cu=np.array([tuple(r) for r in rest],np.float64)[:,:2].mean(0)   # Center of the flat paper (balance point)
    for ax in (1,0):   # 1: tilt along the height (y), 0: along the width (x)
        order=np.lexsort((P[:,2],P[:,ax])).tolist();u=P[:,ax].tolist();z=P[:,2].tolist();hull=[]   # Plain floats: much faster in the loop
        for i in order:   # Lower convex hull of (u, z)
            while len(hull)>=2:
                a,b=hull[-2],hull[-1]
                if (u[b]-u[a])*(z[i]-z[a])-(z[b]-z[a])*(u[i]-u[a])<=0:hull.pop()
                else:break
            hull.append(i)
        c=float(cu[ax]);slope=None
        for a,b in zip(hull,hull[1:]):
            if u[a]<=c<=u[b] and u[b]-u[a]>1e-12:slope=(z[b]-z[a])/(u[b]-u[a]);za=z[a]+slope*(c-u[a]);break
        if not slope:continue
        th=-math.atan(slope);ct,st=math.cos(th),math.sin(th)
        du=P[:,ax]-c;dz=P[:,2]-za
        P[:,ax]=c+du*ct-dz*st;P[:,2]=za+du*st+dz*ct
    return [Vector((float(x),float(y),float(z))) for x,y,z in P]


def fit_inside(coords,left,right,bottom,top):
    """Slide a tilted (back-bent) paper so it stays inside the rectangle it was laid out in.
    Tilting turns it around its middle, which can push one edge past where the flat paper ended."""
    if not coords:return coords
    xs=[c.x for c in coords];ys=[c.y for c in coords]
    def shift(lo,hi,a,b):
        if hi-lo>b-a:return (a+b-lo-hi)/2.   # Wider than the flat paper (rare): center it
        return a-lo if lo<a else b-hi if hi>b else 0.
    dx=shift(min(xs),max(xs),left,right);dy=shift(min(ys),max(ys),bottom,top)
    return [Vector((c.x+dx,c.y+dy,c.z)) for c in coords] if dx or dy else coords


def bend_coordinates(obj,s,lift,kinds=('B',),position='TOP_CENTER',scales=None):
    rest=[p.vector.copy() for p in obj.data.attributes['ps_rest_position'].data]
    if not s.lift_enabled or abs(lift)<=1e-12 or not kinds:return rest
    sign=-1. if lift<0 else 1.;lift=abs(lift)   # Negative lift bends backward (toward the surface side)
    frac=lift/max(obj['height']*s.scale,1e-9)   # Lift ratio (bottom uses height, sides use width)
    if False and s.attach_mode=='TAPE':return tape_coordinates(rest,s,frac,kinds,position)
    left=min(p.x for p in rest);right=max(p.x for p in rest)
    top=max(p.y for p in rest);bottom=min(p.y for p in rest)
    w=right-left;h=top-bottom
    strength=min(1.,frac/max(s.bottom_lift_percent/100,1e-9))
    coords=rest
    roll=s.roll_angle
    if s.lift_random:   # Min-max curl angle per poster
        hi=s.bottom_lift_percent;lo=min(s.lift_min_percent,hi);t=(frac*100-lo)/max(hi-lo,1e-9) if hi>lo else 1.
        roll=min(s.roll_min,s.roll_angle)+(s.roll_angle-min(s.roll_min,s.roll_angle))*max(0.,min(1.,t))
    if False and kinds:   # Large curls only use one kind (bottom+side curling together looks torn)
        group={'B':('B',),'L':('L','R'),'R':('L','R'),'BL':('BL','BR'),'BR':('BL','BR')}[kinds[0]]
        kinds=tuple(k for k in kinds if k in group)
    coords=rest
    for k,(n,c,_) in zip(kinds,curl_folds(s,left,right,bottom,top,kinds)):
        if False:coords=apply_fold(coords,n,c,0.,math.radians(roll))
        else:
            target=frac*(w if k in ('L','R') else h if k=='B' else min(w,h))*(scales or {}).get(k,1.)
            if k=='B' and abs(s.curl_shape-2.)>1e-3:coords=shaped_fold(coords,n,c,target,s.curl_shape)
            else:coords=apply_fold(coords,n,c,target)
    if sign<0:   # Mirror the bend through the paper plane; placement then rests the curled edges on the surface
        coords=[Vector((c.x,c.y,r.z-(c.z-r.z))) for c,r in zip(coords,rest)]
        coords=fit_inside(rest_on_surface(coords,rest),left,right,bottom,top)
    return coords


def migrate_lift_units(s):
    # Convert legacy distances and max-relative minima once, preserving the
    # previous random range. New areas already use the percent schema.
    if not s.is_property_set('bottom_lift_percent') and 'bottom_lift' in s:
        heights=sorted(o['height']*s.scale for o in s.cache.objects) if s.cache else []
        if not heights:return
        middle=len(heights)//2
        reference=heights[middle] if len(heights)%2 else (heights[middle-1]+heights[middle])*.5
        s.bottom_lift_percent=max(0.,min(50.,float(s['bottom_lift'])/max(reference,1e-9)*100))
    if s.lift_percent_schema<1:
        ratio=max(0.,min(1.,float(s.get('lift_min_ratio',.15))))
        s.lift_min_percent=s.bottom_lift_percent*ratio
        s.lift_percent_schema=1


ROT_MAP={}


def rot_axis_map(area):
    """World axis (0 X, 1 Y, 2 Z) -> (paper-local axis, sign) for this area, so the X Y Z buttons follow Blender's world axes.
    Paper-local: 0 tilts top/bottom off the surface, 1 turns around the paper's up axis, 2 spins it flat on the surface."""
    M=area.matrix_world.to_3x3() if isinstance(area,bpy.types.Object) else Matrix.Identity(3)
    cols=[Vector((M[0][i],M[1][i],M[2][i])).normalized() for i in range(3)]
    out={};used=set()
    for _,w,i in sorted(((abs(cols[i][w]),w,i) for w in range(3) for i in range(3)),reverse=True):
        if w in out or i in used:continue
        out[w]=(i,1. if cols[i][w]>=0 else -1.);used.add(i)
    return out


def rot_world(s,w,v):
    """Angle for world axis w: the shared Angle plus the shared Random range times v (-1..1, drawn per axis); 0 when the axis is off."""
    if not getattr(s,'rot_%s_on'%'xyz'[w]):return 0.
    ax='xyz'[w];return getattr(s,'rot_%s_angle'%ax)+v*getattr(s,'rot_%s_rand'%ax)


def inplane_angle(s,v):
    """Spin flat on the surface (it changes each footprint, so placement uses it). v: random value in -1..1."""
    area=s.id_data;m=ROT_MAP.get(area.as_pointer()) if isinstance(area,bpy.types.Object) else None
    if m is None:m=rot_axis_map(area)
    w=next(w for w,(i,_) in m.items() if i==2);return m[w][1]*rot_world(s,w,v)


def migrate_rotation(s):
    """Move older settings onto the X Y Z rotation once: Rotation Range / Tilt / Turn (schema 0), then the shared Angle / Random onto each axis (schema 1)."""
    if s.rot_schema>=2 or not isinstance(s.id_data,bpy.types.Object):return
    if s.rot_schema<1:
        m=rot_axis_map(s.id_data);w_of={i:(w,sg) for w,(i,sg) in m.items()}
        def put(local,rand):
            w,_=w_of[local];setattr(s,'rot_%s_on'%'xyz'[w],True);s.rot_rand=max(s.rot_rand,rand)
        if s.rotation>0:put(2,s.rotation)
        if s.tilt>0:put(0,(s.tilt-min(s.tilt_min,s.tilt))*.5 if s.tilt_random else s.tilt)
        if s.yaw>0:put(1,s.yaw)
    for ax in 'xyz':   # every axis that was on keeps the angle / random it had
        if getattr(s,'rot_%s_on'%ax):setattr(s,'rot_%s_angle'%ax,s.rot_angle);setattr(s,'rot_%s_rand'%ax,s.rot_rand)
    s.rot_schema=2

def instance_lift(s,obj,x,y,ordinal):
    if not s.lift_enabled:return 0.
    maximum=obj['height']*s.scale*s.bottom_lift_percent/100.
    if not s.lift_random:return maximum
    key=('%s|%.7f|%.7f|%d|%d'%(obj['source'],x,y,ordinal,s.lift_seed)).encode()
    value=int.from_bytes(hashlib.blake2b(key,digest_size=8).digest(),'big')/(2**64-1)
    minimum=obj['height']*s.scale*min(s.lift_min_percent,s.bottom_lift_percent)/100.
    return minimum+(maximum-minimum)*value


def set_instance_collection(s,collection):
    if not s.output:return
    mod=s.output.modifiers.get('Poster Scatter') or s.output.modifiers.get('포스터 배치')  # '포스터 배치' = name used by older versions
    if not mod or not mod.node_group:return
    sock=next((x for x in mod.node_group.interface.items_tree if x.name in ('Poster Collection','포스터 컬렉션')),None)  # older Korean socket name
    if sock is None:return
    if hasattr(mod,'properties'):getattr(mod.properties.inputs,sock.identifier).value=collection
    else:mod[sock.identifier]=collection


def curl_region(s,obj,x,y,angle,k,kind):
    """Rectangle (layout coordinates) enclosing the part that bends for lift type k."""
    w=obj['width']*s.scale*k;h=obj['height']*s.scale*k
    if kind=='B':bh=h*(1-s.bend_start);ox,oy,rw,rh=0,-h/2+bh/2,w,bh
    elif kind in ('L','R'):bw=w*s.side_band;ox,oy,rw,rh=(-1 if kind=='L' else 1)*(w/2-bw/2),0,bw,h
    else:leg=min(w,h)*s.corner_size;ox,oy,rw,rh=(-1 if kind=='BL' else 1)*(w/2-leg/2),-h/2+leg/2,leg,leg
    c,sn=math.cos(angle),math.sin(angle)
    return rectangle(x+c*ox-sn*oy,y+sn*ox+c*oy,rw,rh,angle)


def covered_curls(s,catalog,records,extra=()):
    """Press flat when covered: sides covered by later (upper) papers do not lift, and if the bottom is covered the tilt is also 0.
    extra = papers from other areas stacked on this area (all treated as above).
    Returns: (sides that must not lift {index:{kind}}, set of indices whose tilt is removed)"""
    if not s.press:return {},{}
    boxes=[rectangle(x,y,catalog[i]['width']*s.scale*k,catalog[i]['height']*s.scale*k,a) for x,y,i,a,k in records]
    bbs=[aabb(b) for b in boxes];ebs=[aabb(b) for b in extra]
    v_=max(0.,min(1.,s.press_strength))
    base_s=min(1.,v_/.4);strong=max(0.,(v_-.4)/.6)   # 0-0.4: covered part / 0.4-1: whole covered paper -> 1 means fully flat
    def remain(n):   # Papers covered n deep: the one right under the top is pressed hardest, deeper ones less
        return 1.-base_s*(s.press_falloff**max(0,n-1)) if n else 1.
    blocked={};pressed={}
    cell=max(sorted(max(b[2]-b[0],b[3]-b[1]) for b in bbs)[len(bbs)//2] if bbs else 1.,1e-4);grid={}   # Only nearby papers are compared
    span=lambda b:[(i,j) for i in range(int(math.floor(b[0]/cell)),int(math.floor(b[2]/cell))+1) for j in range(int(math.floor(b[1]/cell)),int(math.floor(b[3]/cell))+1)]
    for j,b in enumerate(bbs):
        for c in span(b):grid.setdefault(c,[]).append(j)
    for i,(x,y,idx,a,k) in enumerate(records):
        near=sorted({j for c in span(bbs[i]) for j in grid.get(c,()) if j>i})
        above=[boxes[j] for j in near if aabb_hit(bbs[i],bbs[j]) and not separated(boxes[i],boxes[j])]
        above+=[b for b,eb in zip(extra,ebs) if aabb_hit(bbs[i],eb) and not separated(boxes[i],b)]
        if not above:continue
        for kind in ('B','L','R','BL','BR'):
            region=curl_region(s,catalog[idx],x,y,a,k,kind)
            n=sum(1 for b in above if not separated(region,b))
            if n:blocked.setdefault(i,{})[kind]=max(0.,remain(n))
        h=catalog[idx]['height']*s.scale*k;w=catalog[idx]['width']*s.scale*k;c,sn=math.cos(a),math.sin(a)
        low=rectangle(x+sn*h*.2,y-c*h*.2,w,h*.6,a)   # If the bottom 60% is covered, press the tilt down
        n=sum(1 for b in above if not separated(low,b))
        if n:pressed[i]=max(0.,remain(n))
        if strong>0:   # Strong: covered papers keep only (1-strong) of all lift/curl/tilt and are pressed flat
            whole=1.-strong
            d=blocked.setdefault(i,{})
            for kind in ('B','L','R','BL','BR'):d[kind]=min(d.get(kind,1.),whole)
            pressed[i]=min(pressed.get(i,1.),whole)
    return blocked,pressed


BEND_VERSION=2   # Bump when the bend math changes so saved papers are re-bent instead of reused
BENT_CACHE={}   # Per area: each paper's natural bent shape by bend key. Papers lifted onto others are restored
                # from here on the next update instead of being bent again from scratch.


def sync_bent_instances(area,catalog,records,blocked=None):
    s=area.poster_scatter
    if not s.render_cache:s.render_cache=bpy.data.collections.new('Poster Lift · '+area.name)
    cache=s.render_cache;existing=sorted(cache.objects,key=lambda o:o.name);objects=[]
    # Slots whose source changed reuse a freed mesh of the same source from another slot instead of copying a new one
    want=['%d|%s'%(catalog[r[2]].data.as_pointer(),catalog[r[2]].get('ps_build','')) for r in records];pool={}
    old=BENT_CACHE.get(area.as_pointer(),{});keep={}
    for j,obj in enumerate(existing):
        if j>=len(records) or obj.get('source_mesh')!=want[j]:
            pool.setdefault(obj.get('source_mesh'),[]).append(obj.data)
    holder=bpy.data.meshes.get('_ps_empty') or bpy.data.meshes.new('_ps_empty')
    for j,obj in enumerate(existing):
        if j>=len(records) or obj.get('source_mesh')!=want[j]:obj.data=holder;obj['bend_key']=''
    curved_area=area_flat(area.data) is not None
    for j,(x,y,idx,angle,*_) in enumerate(records):
        source=catalog[idx];source_id=want[j]
        if j<len(existing):
            obj=existing[j]
            if obj.data==holder:
                lst=pool.get(source_id);obj.data=lst.pop() if lst else source.data.copy()
        else:
            lst=pool.get(source_id)
            obj=bpy.data.objects.new('Lift %04d · %s'%(j,area.name),lst.pop() if lst else source.data.copy());cache.objects.link(obj)
        obj['ps_owned']=True;obj['source_mesh']=source_id;obj['source']=source['source']
        if source.get('poster_source_object'):obj['poster_source_object']=source['poster_source_object']
        lift=instance_lift(s,source,x,y,j);obj['requested_lift']=lift
        if False and s.attach_mode=='TAPE':
            position=tape_position_for(s,source,x,y,j);base=('B','L','R')
        else:position='';base=curl_kinds(s,source,x,y,j)
        scales=(blocked or {}).get(j,{})   # The covered side only keeps what is left after pressing
        kinds=tuple(k for k in base if scales.get(k,1.)>1e-3);obj['curl']=' '.join(kinds)+(' · '+position if position else '')
        # Skip rewriting vertices if the bent shape is the same as last time (e.g. only the position changed)
        key=repr((BEND_VERSION,source_id,len(obj.data.vertices),round(lift,7),kinds,sorted(scales.items()),s.lift_enabled,round(s.scale,6),
                  round(s.bottom_lift_percent,5),round(s.bend_start,5),round(s.side_band,5),round(s.corner_size,5),round(s.curl_shape,4)))
        nco=3*len(obj.data.vertices);co=old.get(key)
        if curved_area or obj.get('bend_key')!=key:
            if co is None or len(co)!=nco:   # Not bent like this last time either: bend now
                co=np.array([c for v in bend_coordinates(source,s,lift,kinds,position,scales) for c in v],np.float32)
            obj.data.vertices.foreach_set('co',co)   # Write in one go
            obj.data.update();obj['bend_key']='' if curved_area else key
        elif co is None or len(co)!=nco:   # Already in this shape: remember it for when it gets lifted onto papers below
            co=np.empty(nco,np.float32);obj.data.vertices.foreach_get('co',co)
        keep[key]=co
        objects.append(obj)
    for obj in existing[len(records):]:bpy.data.objects.remove(obj,do_unlink=True)
    for lst in pool.values():
        for mesh in lst:
            if mesh.users==0:bpy.data.meshes.remove(mesh)
    if holder.users==0:bpy.data.meshes.remove(holder)
    BENT_CACHE[area.as_pointer()]=keep
    set_instance_collection(s,cache)
    return objects


def refresh_sources(area):
    s=area.poster_scatter;items=sources(s.collection)
    if not items:raise ValueError('Please choose a collection that contains mesh posters.')
    prepared=[];skipped=[]
    try:
        for o in items:
            try:mesh,w,h=source_geometry(o,s)
            except ValueError:skipped.append(o.name);continue   # Skip anything that is not a flat poster (test cylinders etc.)
            prepared.append((o,mesh,w,h))
    except Exception:
        for _,mesh,_,_ in prepared:bpy.data.meshes.remove(mesh)
        raise
    s['ps_skipped']=', '.join(skipped)
    if not prepared:raise ValueError('No flat posters. Excluded: '+', '.join(skipped[:5]))
    cache=s.cache
    if not cache:
        cache=bpy.data.collections.new('Poster Scatter Sources · '+area.name);s.cache=cache
    for o in list(cache.objects):
        mesh=o.data;bpy.data.objects.remove(o,do_unlink=True)
        if mesh.users==0:bpy.data.meshes.remove(mesh)
    sizes=sorted(set(round(max(w,h),6) for _,_,w,h in prepared));build='%x'%time.time_ns()
    for i,(original,mesh,w,h) in enumerate(prepared):
        o=bpy.data.objects.new('%04d · %s'%(i,original.name),mesh);cache.objects.link(o);o['ps_owned']=True
        o['ps_build']=build   # New sources each refresh: a freed mesh's memory address can come back, this tells them apart
        rank=bisect.bisect_left(sizes,round(max(w,h),6))
        group=1 if len(sizes)==1 else min(2,rank*3//len(sizes))
        o['width']=w;o['height']=h;o['group']=group;o['source']=original.name
        o['poster_source_id']=original.get('poster_id','')
        o['poster_source_object']=original
        o['center_x']=(min(v.co.x for v in mesh.vertices)+max(v.co.x for v in mesh.vertices))*.5
        o['center_y']=(min(v.co.y for v in mesh.vertices)+max(v.co.y for v in mesh.vertices))*.5
    s.source_count=len(prepared);apply_auto_count(s)
    s.cached_sources=source_signature(s.collection)
    s.cached_topology=topology_signature(s)
    set_instance_collection(s,cache)


def create_area(context,target,selected_only=True,build=True):
    if target.type!='MESH':raise ValueError('Please select mesh faces of a wall or floor.')
    if target.mode=='EDIT':target.update_from_editmode()
    polys=[p for p in target.data.polygons if p.select or not selected_only]
    if not polys:raise ValueError('Please select the faces to scatter on.')
    world=target.matrix_world
    normal=world.to_3x3().inverted().transposed()@polys[0].normal;normal.normalize()
    origin=world@target.data.vertices[polys[0].vertices[0]].co
    up=Vector((0,0,1)) if abs(normal.z)<.95 else Vector((0,1,0))
    up=(up-normal*up.dot(normal)).normalized();right=up.cross(normal).normalized()
    frame=Matrix(((right.x,up.x,normal.x,origin.x),(right.y,up.y,normal.y,origin.y),(right.z,up.z,normal.z,origin.z),(0,0,0,1)))
    ids=sorted(set(i for p in polys for i in p.vertices));mapping={idx:i for i,idx in enumerate(ids)}
    coords=[frame.inverted()@(world@target.data.vertices[i].co) for i in ids]
    curved=any(abs(v.z)>.0005 for v in coords)
    mesh=bpy.data.meshes.new('Poster Paint Surface')
    mesh.from_pydata([(v.x,v.y,v.z if curved else 0) for v in coords],[],[[mapping[i] for i in p.vertices] for p in polys]);mesh.update()
    bm=bmesh.new();bm.from_mesh(mesh)
    step=context.scene.poster_scatter_setup.paint_step
    if curved:   # Curved surface: split each edge by the paint spacing, then unfold as triangles
        for e in list(bm.edges):
            n=min(60,max(0,math.ceil(e.calc_length()/step)-1))
            if n:bmesh.ops.subdivide_edges(bm,edges=[e],cuts=n,use_grid_fill=False)
        bmesh.ops.triangulate(bm,faces=list(bm.faces))
        bm.to_mesh(mesh);bm.free();mesh.calc_loop_triangles()
        verts,faces,flat=unfold_surface([v.co.copy() for v in mesh.vertices],[tuple(t.vertices) for t in mesh.loop_triangles],
                                         (frame.inverted().to_3x3()@Vector((0,0,1))).normalized())
        mesh.clear_geometry();mesh.from_pydata(verts,[],faces);mesh.update()
        a=mesh.attributes.new('ps_flat','FLOAT_VECTOR','POINT');a.data.foreach_set('vector',[c for f in flat for c in (f.x,f.y,0.)])
    else:
        longest=max((e.calc_length() for e in bm.edges),default=0)
        cuts=min(100,max(1,math.ceil(longest/step)-1))
        bmesh.ops.subdivide_edges(bm,edges=list(bm.edges),cuts=cuts,use_grid_fill=True)
        bm.to_mesh(mesh);bm.free()
    for name,value in [(MASK,1),(SEED,0)]:
        a=mesh.color_attributes.new(name=name,type='FLOAT_COLOR',domain='POINT')
        a.data.foreach_set('color',np.tile([value,value,value,1],len(mesh.vertices)))
    mesh.color_attributes.active_color=mesh.color_attributes[MASK]
    home=ps_home_collection(context,target)
    area=bpy.data.objects.new('Poster Scatter Area · '+target.name,mesh);home.objects.link(area);area.matrix_world=frame
    area.hide_render=True;area['ps_owned']=True;area.display_type='BOUNDS'   # Show faces only while painting
    ps_area_invisible(area)
    if not getattr(bpy.context.scene,'ps_show_areas',True):
        try:area.hide_set(True)
        except RuntimeError:pass
    area.location+=normal*.0001
    s=area.poster_scatter;s.enabled=True;s.lift_percent_schema=1;s.collection=context.scene.poster_scatter_setup.collection;s.curved=curved
    s.check_step=context.scene.poster_scatter_setup.paint_step*.5
    outmesh=bpy.data.meshes.new('Poster Scatter Points');out=bpy.data.objects.new('Poster Scatter Result · '+target.name,outmesh);home.objects.link(out)
    out.parent=area;out['ps_owned']=True;s.output=out;out.hide_viewport=not getattr(context.scene,'ps_show_results',True)
    mod=out.modifiers.new('Poster Scatter','NODES');mod.node_group=make_node()
    if s.collection and build:
        try:refresh_sources(area);rebuild(area)
        except ValueError as exc:s.status=str(exc)
    return area

def area_flat(mesh):
    a=mesh.attributes.get('ps_flat')
    if a is None or a.domain!='POINT' or len(a.data)!=len(mesh.vertices):return None
    buf=np.empty(len(mesh.vertices)*3,np.float32);a.data.foreach_get('vector',buf);return buf.reshape(-1,3)


def flat_points(mesh):
    """Unfolded plane coordinates used for layout (flat areas as-is, curved areas unfolded)."""
    f=area_flat(mesh)
    if f is None:return [v.co.copy() for v in mesh.vertices]
    return [Vector((float(x),float(y),0.)) for x,y,_ in f]


class SurfaceMap:
    """Unfolded plane coordinates <-> real curved surface (area-local 3D)."""
    def __init__(self,mesh):
        mesh.calc_loop_triangles()
        self.F=flat_points(mesh);self.P=[v.co.copy() for v in mesh.vertices];self.N=[v.normal.copy() for v in mesh.vertices]
        self.tris=[tuple(t.vertices) for t in mesh.loop_triangles]
        self.flat=BVHTree.FromPolygons(self.F,self.tris,all_triangles=True)
        self.surface=BVHTree.FromPolygons(self.P,self.tris,all_triangles=True)
    def map(self,x,y):
        q=Vector((x,y,0.));idx=self.flat.ray_cast(Vector((x,y,1.)),Vector((0,0,-1.)),2.)[2]
        if idx is None:idx=self.flat.find_nearest(q)[2]   # Outside the area, extend the nearest face
        if idx is None:return None
        i,j,k=self.tris[idx];a,b,c=self.F[i],self.F[j],self.F[k]
        den=(b.x-a.x)*(c.y-a.y)-(c.x-a.x)*(b.y-a.y)
        if abs(den)<1e-14:return self.P[i].copy(),self.N[i].copy()
        u=((q.x-a.x)*(c.y-a.y)-(c.x-a.x)*(q.y-a.y))/den;v=((b.x-a.x)*(q.y-a.y)-(q.x-a.x)*(b.y-a.y))/den;w=1-u-v
        p=self.P[i]*w+self.P[j]*u+self.P[k]*v
        n=self.N[i]*w+self.N[j]*u+self.N[k]*v
        return p,(n.normalized() if n.length>1e-9 else self.N[i].copy())
    def to_flat(self,idx,co):
        i,j,k=self.tris[idx];f=barycentric_transform(co,self.P[i],self.P[j],self.P[k],self.F[i],self.F[j],self.F[k])
        return Vector((f.x,f.y,0.))
    def frame(self,x,y,e):
        """Tangent frame at (x,y): position, right, up, normal."""
        p,n=self.map(x,y);px=self.map(x+e,y)[0]-self.map(x-e,y)[0];py=self.map(x,y+e)[0]-self.map(x,y-e)[0]
        up=py-n*py.dot(n)
        if up.length<1e-12:up=Vector((0,0,1))-n*n.z
        up.normalize();right=up.cross(n)
        if right.dot(px)<0:right=-right
        return p,right,up,n


def unfold_surface(coords,tris,world_up=Vector((0,0,1))):
    """Unfold a curved surface like paper (triangle edge lengths preserved). Points are split where it cannot stay connected (e.g. a cylinder seam)."""
    edges={}
    for t,(a,b,c) in enumerate(tris):
        for u,v in ((a,b),(b,c),(c,a)):edges.setdefault((min(u,v),max(u,v)),[]).append(t)
    import heapq
    corner=[None]*len(tris);shift_x=0.;size=max((coords[i]-coords[j]).length for a,b,c in tris[:50] for i,j in ((a,b),(b,c)))
    cent=[(coords[a]+coords[b]+coords[c])/3 for a,b,c in tris]
    # Unfold by distance from the center: closed surfaces like cylinders split cleanly on the far side
    mid=sum(cent,Vector())/max(1,len(cent))
    seeds=sorted(range(len(tris)),key=lambda t:(cent[t]-mid).length)
    for seed in seeds:
        if corner[seed] is not None:continue
        a,b,c=tris[seed];p0=coords[a];n=(coords[b]-p0).cross(coords[c]-p0)
        if n.length<1e-14:continue
        n.normalize();up=world_up-n*n.dot(world_up)   # Up in the unfolded plane = real up
        if up.length<1e-6:up=Vector((0,1,0))-n*n.y
        up.normalize();right=up.cross(n)
        corner[seed]={v:Vector(((coords[v]-p0).dot(right),(coords[v]-p0).dot(up))) for v in (a,b,c)}
        origin=sum(corner[seed].values(),Vector((0,0)))/3
        island=[seed];queue=[(0.,seed)]
        while queue:
            dist,t=heapq.heappop(queue)
            tv=tris[t]
            for u,v in ((tv[0],tv[1]),(tv[1],tv[2]),(tv[2],tv[0])):
                o=next(x for x in tv if x not in (u,v))
                for nb in edges[(min(u,v),max(u,v))]:
                    if nb==t or corner[nb] is not None:continue
                    w=next(x for x in tris[nb] if x not in (u,v))
                    e3=coords[v]-coords[u];L=e3.length
                    if L<1e-14:continue
                    eh=e3/L;d3=coords[w]-coords[u];along=d3.dot(eh);perp=(d3-eh*along).length
                    fa=corner[t][u];fb=corner[t][v];e2=fb-fa
                    if e2.length<1e-14:continue
                    e2.normalize();n2=Vector((-e2.y,e2.x))
                    if (corner[t][o]-fa).dot(n2)>0:n2=-n2
                    fw=fa+e2*along+n2*perp
                    corner[nb]={u:fa.copy(),v:fb.copy(),w:fw};island.append(nb)
                    # Closest to the start point in the unfolded plane first: closed surfaces split cleanly exactly on the far side
                    heapq.heappush(queue,(((fa+fb+fw)/3-origin).length,nb))
        # Disconnected pieces are unfolded side by side
        lo=min(p.x for t in island for p in corner[t].values());hi=max(p.x for t in island for p in corner[t].values())
        for t in island:
            for key in corner[t]:corner[t][key].x+=shift_x-lo
        shift_x+=hi-lo+size*4
    tol=max(size*1e-3,1e-7);verts=[];flat=[];faces=[];clusters={}
    for t,tv in enumerate(tris):
        if corner[t] is None:continue
        face=[]
        for v in tv:
            f=corner[t][v];group=clusters.setdefault(v,[])
            hit=next((i for i,g in group if (flat[i]-f).length<tol),None)
            if hit is None:hit=len(verts);verts.append(coords[v].copy());flat.append(f.copy());group.append((hit,f))
            face.append(hit)
        faces.append(face)
    return verts,faces,flat


def colors(mesh,name):
    attr=mesh.color_attributes.get(name)
    if attr is None or attr.domain!='POINT':raise ValueError(name+' color attribute is missing or not on the point domain.')
    data=np.empty(len(mesh.vertices)*4,dtype=np.float32);attr.data.foreach_get('color',data);return data.reshape((-1,4))

def separated(a,b):
    # SAT for rotated rectangles: True when they do not overlap (touching counts as apart).
    for poly in (a,b):
        for k in (0,1):
            p0=poly[k];p1=poly[(k+1)%4];ax=p0.y-p1.y;ay=p1.x-p0.x
            da=[v.x*ax+v.y*ay for v in a];db=[v.x*ax+v.y*ay for v in b]
            if max(da)<=min(db)+1e-10 or max(db)<=min(da)+1e-10:return True
    return False

def rectangle(x,y,w,h,angle):
    co,si=math.cos(angle),math.sin(angle)
    return [Vector((x+co*dx-si*dy,y+si*dx+co*dy)) for dx,dy in [(-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2)]]

def polygon_area(poly):
    return abs(sum(a.x*b.y-a.y*b.x for a,b in zip(poly,poly[1:]+poly[:1])))*.5 if len(poly)>2 else 0.

def footprint(P,x,y,angle,pad=1e-6):
    """Rectangle turned like the placement that holds the paper's real outline seen from above
    (curls, tilts and back bends move the paper off its layout rectangle)."""
    c,sn=math.cos(angle),math.sin(angle);dx=P[:,0]-x;dy=P[:,1]-y
    u=dx*c+dy*sn;v=dy*c-dx*sn
    u0,u1,v0,v1=float(u.min())-pad,float(u.max())+pad,float(v.min())-pad,float(v.max())+pad
    return [Vector((x+c*a-sn*b,y+sn*a+c*b)) for a,b in ((u0,v0),(u1,v0),(u1,v1),(u0,v1))]


def aabb(poly):
    xs=[p.x for p in poly];ys=[p.y for p in poly];return (min(xs),min(ys),max(xs),max(ys))


def aabb_hit(a,b):
    return a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3]


def overlap_area(a,b):
    out=list(a)
    for p,q in zip(b,b[1:]+b[:1]):
        current=out;out=[]
        if not current:break
        edge=q-p
        def side(v):return edge.x*(v.y-p.y)-edge.y*(v.x-p.x)
        prev=current[-1];ds=side(prev)
        for point in current:
            de=side(point)
            if (de>=0)!=(ds>=0):out.append(prev+(point-prev)*(ds/(ds-de)))
            if de>=0:out.append(point)
            prev=point;ds=de
    return polygon_area(out)

class BoxIndex:
    """Placed rectangles plus their bounding boxes in one array, so a new candidate is only compared
    with the ones near it (going through every placed one on each try gets slow with many papers)."""
    def __init__(self,rects=()):
        self.rects=[];self.bb=np.zeros((64,4));self.n=0
        for r in rects:self.append(r)
    def append(self,r):
        if self.n==len(self.bb):self.bb=np.vstack([self.bb,np.zeros_like(self.bb)])
        self.bb[self.n]=aabb(r);self.n+=1;self.rects.append(r)
    def __len__(self):return self.n
    def __iter__(self):return iter(self.rects)
    def near(self,b):
        B=self.bb[:self.n]
        return [self.rects[k] for k in np.flatnonzero((B[:,0]<b[2])&(b[0]<B[:,2])&(B[:,1]<b[3])&(b[1]<B[:,3]))]


def placement_clear(box,others,s):
    bb=aabb(box)   # Skip precise checks for distant ones
    near=others.near(bb) if isinstance(others,BoxIndex) else [o for o in others if aabb_hit(bb,aabb(o))]
    if not s.allow_overlap:return all(separated(box,other) for other in near)
    ab=polygon_area(box)
    return all(overlap_area(box,other)<=min(ab,polygon_area(other))*s.overlap_ratio+1e-10 for other in near)

def raster_tris(P,T,vals,gx0,gy0,dx,dy,nx,ny):
    """Bake a triangle mesh (P: vertex xy, T: triangles, vals: vertex values (N,C)) onto grid points (gx0+i*dx, gy0+j*dy) in one go.
    Returns: (ny,nx,C) values and which grid points fell inside a triangle (ny,nx)."""
    C=vals.shape[1];out=np.zeros((ny*nx,C),np.float32);hit=np.zeros(ny*nx,bool)
    A=P[T[:,0]];B=P[T[:,1]];Cc=P[T[:,2]]
    den=(B[:,1]-Cc[:,1])*(A[:,0]-Cc[:,0])+(Cc[:,0]-B[:,0])*(A[:,1]-Cc[:,1])
    good=np.abs(den)>1e-18
    lo=np.minimum(np.minimum(A,B),Cc);hi=np.maximum(np.maximum(A,B),Cc)
    i0=np.clip(np.floor((lo[:,0]-gx0)/dx),0,nx-1).astype(np.int64);i1=np.clip(np.ceil((hi[:,0]-gx0)/dx),0,nx-1).astype(np.int64)
    j0=np.clip(np.floor((lo[:,1]-gy0)/dy),0,ny-1).astype(np.int64);j1=np.clip(np.ceil((hi[:,1]-gy0)/dy),0,ny-1).astype(np.int64)
    span=np.maximum(i1-i0,j1-j0)+1
    def bake(sel,K):
        if not len(sel):return
        d=np.arange(K)
        ii=i0[sel][:,None,None]+d[None,None,:];jj=j0[sel][:,None,None]+d[None,:,None]
        ok=(ii<=i1[sel][:,None,None])&(jj<=j1[sel][:,None,None])
        X=gx0+ii*dx;Y=gy0+jj*dy
        a,b,c,dn=A[sel][:,None,None,:],B[sel][:,None,None,:],Cc[sel][:,None,None,:],den[sel][:,None,None]
        l1=((b[...,1]-c[...,1])*(X-c[...,0])+(c[...,0]-b[...,0])*(Y-c[...,1]))/dn
        l2=((c[...,1]-a[...,1])*(X-c[...,0])+(a[...,0]-c[...,0])*(Y-c[...,1]))/dn;l3=1-l1-l2
        ok&=(l1>=-1e-9)&(l2>=-1e-9)&(l3>=-1e-9)
        t=T[sel];cell=(jj*nx+ii)[ok]
        v=(l1[...,None]*vals[t[:,0]][:,None,None,:]+l2[...,None]*vals[t[:,1]][:,None,None,:]+l3[...,None]*vals[t[:,2]][:,None,None,:])[ok]
        out[cell]=v;hit[cell]=True
    for K in (2,4,8,16,32):bake(np.flatnonzero(good&(span<=K)&((span>K//2) if K>2 else True)),K)
    for t_ in np.flatnonzero(good&(span>32)):bake(np.array([t_]),int(span[t_]))
    return out.reshape(ny,nx,C),hit.reshape(ny,nx)


MASK_GRIDS={}


def mask_grid(key,verts,tris,mask,bounds,step):
    """Bake the placeable area into a grid once (again only when the paint changes) to test quickly whether a paper fits.
    Cached per area; all triangles are baked at once (vectorized)."""
    hit=MASK_GRIDS.get(key[0])
    if hit and hit[0]==key:return hit[1]
    x0,x1,y0,y1=bounds;step=max(step,(x1-x0)/1500,(y1-y0)/1500)
    nx=int(math.ceil((x1-x0)/step))+1;ny=int(math.ceil((y1-y0)/step))+1
    val=np.full(ny*nx,-1.,np.float32)
    P=np.array([(v.x,v.y) for v in verts],np.float64);M=mask[:,0].astype(np.float64)
    T=np.asarray(tris,np.int64).reshape(-1,3)
    A=P[T[:,0]];B=P[T[:,1]];C=P[T[:,2]]
    den=(B[:,1]-C[:,1])*(A[:,0]-C[:,0])+(C[:,0]-B[:,0])*(A[:,1]-C[:,1])
    good=np.abs(den)>1e-18
    lo=np.minimum(np.minimum(A,B),C);hi=np.maximum(np.maximum(A,B),C)
    i0=np.clip(np.floor((lo[:,0]-x0)/step),0,nx-1).astype(np.int64);i1=np.clip(np.ceil((hi[:,0]-x0)/step),0,nx-1).astype(np.int64)
    j0=np.clip(np.floor((lo[:,1]-y0)/step),0,ny-1).astype(np.int64);j1=np.clip(np.ceil((hi[:,1]-y0)/step),0,ny-1).astype(np.int64)
    span=np.maximum(i1-i0,j1-j0)+1
    def bake(sel,K):
        if not len(sel):return
        d=np.arange(K)
        ii=i0[sel][:,None,None]+d[None,None,:];jj=j0[sel][:,None,None]+d[None,:,None]
        ok=(ii<=i1[sel][:,None,None])&(jj<=j1[sel][:,None,None])
        X=x0+ii*step;Y=y0+jj*step
        a,b,c,dn=A[sel][:,None,None,:],B[sel][:,None,None,:],C[sel][:,None,None,:],den[sel][:,None,None]
        l1=((b[...,1]-c[...,1])*(X-c[...,0])+(c[...,0]-b[...,0])*(Y-c[...,1]))/dn
        l2=((c[...,1]-a[...,1])*(X-c[...,0])+(a[...,0]-c[...,0])*(Y-c[...,1]))/dn;l3=1-l1-l2
        ok&=(l1>=-1e-9)&(l2>=-1e-9)&(l3>=-1e-9)
        t=T[sel];v=l1*M[t[:,0]][:,None,None]+l2*M[t[:,1]][:,None,None]+l3*M[t[:,2]][:,None,None]
        np.maximum.at(val,(jj*nx+ii)[ok],v[ok].astype(np.float32))
    # Group triangles of similar size and process at once (very large triangles separately)
    for K in (2,4,8,16,32):
        sel=np.flatnonzero(good&(span<=K)&(span>K//2 if K>2 else True));bake(sel,K)
    for t_ in np.flatnonzero(good&(span>32)):   # Rare large triangles
        K=int(span[t_]);sel=np.array([t_]);bake(sel,K)
    val=val.reshape(ny,nx)
    ok=val>=.01;e=ok.copy()   # Only allow one cell inward so nothing sticks out half a cell at the border
    e[1:,:]&=ok[:-1,:];e[:-1,:]&=ok[1:,:];e[:,1:]&=ok[:,:-1];e[:,:-1]&=ok[:,1:]
    grid=(x0,y0,step,e)
    if len(MASK_GRIDS)>8:MASK_GRIDS.clear()
    MASK_GRIDS[key[0]]=(key,grid);return grid


def footprint_fits(sample,x,y,w,h,angle,step):
    co,si=math.cos(angle),math.sin(angle)
    nx=min(40,max(2,math.ceil(w/step)));ny=min(40,max(2,math.ceil(h/step)))
    g=getattr(sample,'grid',None)
    if g is not None:   # Fast check: look up the pre-baked grid at once
        gx0,gy0,gs,ok=g
        u=(np.arange(nx+1)/nx-.5)*w;v=(np.arange(ny+1)/ny-.5)*h;U,V=np.meshgrid(u,v)
        ix=np.rint((x+co*U-si*V-gx0)/gs).astype(np.int64);iy=np.rint((y+si*U+co*V-gy0)/gs).astype(np.int64)
        if ix.min()<0 or iy.min()<0 or ix.max()>=ok.shape[1] or iy.max()>=ok.shape[0]:return False
        return bool(ok[iy,ix].all())
    for iy in range(ny+1):
        for ix in range(nx+1):
            dx=(ix/nx-.5)*w;dy=(iy/ny-.5)*h
            hit=sample(x+co*dx-si*dy,y+si*dx+co*dy)
            if hit is None or hit[0][0]<.01:return False
    return True

def ensure_repeat_ranges(s):
    if s.repeat_ranges:return
    for upper,limit in ((1.,REPEAT_DEFAULT),):
        rule=s.repeat_ranges.add();rule['upper']=upper;rule.limit=limit


def repeat_caps(s,catalog):
    if not s.repeat:return [1]*len(catalog)
    if not s.repeat_limited:return [None]*len(catalog)
    ensure_repeat_ranges(s)
    areas=[o['width']*o['height'] for o in catalog]
    if not areas:return []
    smallest,largest=min(areas),max(areas);span=largest-smallest;caps=[]
    for area in areas:
        # Equal-size collections use the middle band; uniform scale does not change the ratio.
        position=(area-smallest)/span if span>max(largest,1e-12)*1e-7 else .5
        for j,rule in enumerate(s.repeat_ranges):
            if position<rule.upper-1e-7 or j==len(s.repeat_ranges)-1:
                caps.append(rule.limit);break
    return caps


def source_usage(catalog,records):
    counts=[0]*len(catalog)
    for r in records:counts[r[2]]+=1
    return counts


def quota_available(caps,counts,idx):
    return caps[idx] is None or counts[idx]<caps[idx]


def packed_records(s,catalog,sample,bounds,fixed=(),obstacles=()):
    # Conservative raster packing: reserve rotated bounding boxes, then verify
    # the actual footprint. Source dimensions/UVs are never resized to fit a gap.
    if not s.count or not catalog:return []
    x0,x1,y0,y1=bounds;spanx=x1-x0;spany=y1-y0
    smallest=min(min(o['width'],o['height'])*s.scale for o in catalog)
    step=max(min(s.check_step,smallest/8),max(spanx,spany)/192,1e-5)
    nx=max(1,math.ceil(spanx/step));ny=max(1,math.ceil(spany/step))
    dx=spanx/nx;dy=spany/ny
    blocked=np.ones((ny,nx),dtype=bool)
    field=np.zeros((ny,nx,5),dtype=float)
    src=getattr(sample,'mesh',None)
    if src is not None:   # Bake all cells at once instead of measuring one by one
        P,T,mask,seeds=src
        vals=np.stack([mask[:,0],seeds[:,0]],1).astype(np.float64)
        v,hit=raster_tris(P,T,vals,x0+.5*dx,y0+.5*dy,dx,dy,nx,ny)
        field[...,0]=np.clip(v[...,0],0,1)*hit;field[...,1:4]=hit[...,None];field[...,4]=np.clip(v[...,1],0,1)*hit
        blocked=~hit|(v[...,0]<.01)
    else:
      for iy in range(ny):
        for ix in range(nx):
            hit=sample(x0+(ix+.5)*dx,y0+(iy+.5)*dy)
            if hit is not None:
                m,g,local=hit
                field[iy,ix]=[float(np.clip(m[0],0,1)),*np.maximum(g[:3],0),float(np.clip(local[0],0,1))]
                blocked[iy,ix]=m[0]<.01
    rng=random.Random(s.seed);records=[];counts=source_usage(catalog,fixed);caps=repeat_caps(s,catalog);anchors=[]
    filled=np.zeros_like(blocked)
    occupied=BoxIndex()
    for x,y,idx,angle,k in fixed:
        obj=catalog[idx];margin=0 if s.allow_overlap else s.gap
        box=rectangle(x,y,obj['width']*s.scale*k+margin,obj['height']*s.scale*k+margin,angle);occupied.append(box)
        ix0=max(0,math.floor((min(p.x for p in box)-x0)/dx));ix1=min(nx,math.ceil((max(p.x for p in box)-x0)/dx))
        iy0=max(0,math.floor((min(p.y for p in box)-y0)/dy));iy1=min(ny,math.ceil((max(p.y for p in box)-y0)/dy))
        filled[iy0:iy1,ix0:ix1]=True
    for box in obstacles:   # Fill Empty Space: papers of the layers below are packed around, not dropped afterwards
        occupied.append(box)
        ix0=max(0,math.floor((min(p.x for p in box)-x0)/dx));ix1=min(nx,math.ceil((max(p.x for p in box)-x0)/dx))
        iy0=max(0,math.floor((min(p.y for p in box)-y0)/dy));iy1=min(ny,math.ceil((max(p.y for p in box)-y0)/dy))
        if ix1>ix0 and iy1>iy0:filled[iy0:iy1,ix0:ix1]=True
    # Regional quotas are soft preferences, weighted by paintable area. They
    # never reject a valid remaining gap or impose a visible placement grid.
    region_x=np.minimum(np.arange(nx)*4//nx,3)
    region_y=np.minimum(np.arange(ny)*4//ny,3)
    region_map=region_y[:,None]*4+region_x[None,:]
    capacity=np.bincount(region_map.ravel(),weights=(~blocked).ravel(),minlength=16).astype(float)
    capacity/=max(1.,capacity.sum())
    regional=np.zeros((3,16),dtype=float);placed_centers=[]
    def record_center(x,y,idx):
        px=(x-x0)/spanx;py=(y-y0)/spany;group=int(catalog[idx]['group'])
        region=min(3,max(0,int(py*4)))*4+min(3,max(0,int(px*4)))
        regional[group,region]+=1;placed_centers.append((px,py,group))
    for x,y,idx,*_ in fixed:record_center(x,y,idx)
    largest_group=max(int(o['group']) for o in catalog)
    anchor_budget=min(12,max(1,math.ceil(s.count*.08)))
    if not s.repeat:anchor_budget=min(anchor_budget,sum(int(o['group'])==largest_group for o in catalog))
    sizes=[(o['width']*s.scale,o['height']*s.scale) for o in catalog]
    integ={}
    def integrals():   # Recompute only per placement (not rebuilt per candidate)
        if integ.get('n')!=len(occupied):
            occ=blocked if s.allow_overlap else blocked|filled
            integ['occ']=np.pad(occ.astype(np.int32),((1,0),(1,0))).cumsum(0).cumsum(1)
            integ['ink']=np.pad(filled.astype(np.int32),((1,0),(1,0))).cumsum(0).cumsum(1);integ['n']=len(occupied)
        return integ['occ'],integ['ink']
    while len(records)<s.count:
        # One copy of each source per round keeps repeated originals diverse.
        order=list(range(len(catalog)));rng.shuffle(order)
        order.sort(key=lambda i:-(sizes[i][0]*sizes[i][1]))
        added=0
        for idx in order:
            if len(records)>=s.count:break
            if not quota_available(caps,counts,idx):continue
            w,h=sizes[idx];angle=inplane_angle(s,rng.uniform(-1,1))
            angles=[angle,0.0] if abs(angle)>1e-6 else [0.0]
            placed=False
            for angle in angles:
                co,si=abs(math.cos(angle)),abs(math.sin(angle))
                margin=0 if s.allow_overlap else s.gap
                cw=max(1,math.ceil(((w+margin)*co+(h+margin)*si)/dx))
                ch=max(1,math.ceil(((w+margin)*si+(h+margin)*co)/dy))
                if cw>nx or ch>ny:continue
                integral,ink=integrals()
                free=(integral[ch:,cw:]-integral[:-ch,cw:]-integral[ch:,:-cw]+integral[:-ch,:-cw])==0
                if s.allow_overlap:
                    free&=(ink[ch:,cw:]-ink[:-ch,cw:]-ink[ch:,:-cw]+ink[:-ch,:-cw])<=cw*ch*s.overlap_ratio
                yy,xx=np.nonzero(free)
                if not len(xx):continue
                cy=np.minimum(yy+ch//2,ny-1);cx=np.minimum(xx+cw//2,nx-1)
                f=field[cy,cx];channel=3-int(catalog[idx]['group'])
                total=f[:,1:4].max(axis=1)
                weight=np.divide(f[:,channel],total,out=np.zeros(len(f)),where=total>1e-8)
                # Stable local noise makes gray masks and blended size paint
                # probabilities, even when packing retries a cell many times.
                seed_values=np.floor(f[:,4]*len(catalog)).astype(np.int64)
                noise=((cx*73856093+cy*19349663+s.seed*83492791+seed_values*2654435761)&0x7fffffff)/2147483648.0
                color_noise=((cx*19349663+cy*83492791+(idx+1)*73856093+s.seed*2654435761+seed_values*97531)&0x7fffffff)/2147483648.0
                ok=(noise<f[:,0])&(color_noise<weight)
                xx=xx[ok];yy=yy[ok];noise=noise[ok]
                spreading=int(catalog[idx]['group'])==largest_group and len(anchors)<anchor_budget
                if spreading:
                    # Pick from seeded random sites across the whole painted area.
                    # Best-of-32 spacing avoids a cluster without forcing a grid
                    # or always starting at the same wall corner.
                    shortlist=np.array(rng.sample(range(len(xx)),min(64,len(xx))),dtype=int)
                    px=(xx[shortlist]+cw/2)/nx;py=(yy[shortlist]+ch/2)/ny
                    if anchors:
                        distance=np.minimum.reduce([(px-ax)**2+(py-ay)**2 for ax,ay in anchors])
                        shortlist=shortlist[np.argsort(-distance,kind='stable')]
                    candidates=shortlist
                else:
                    # First balance each size band across the painted surface.
                    # Contact only breaks near-ties; it must not grow a cluster.
                    px=(xx+cw/2)/nx;py=(yy+ch/2)/ny
                    regions=np.minimum((py*4).astype(int),3)*4+np.minimum((px*4).astype(int),3)
                    group=int(catalog[idx]['group'])
                    group_load=regional[group]/np.maximum(capacity,.001)
                    total_load=regional.sum(axis=0)/np.maximum(capacity,.001)
                    priority=group_load[regions]/max(1.,regional[group].sum())
                    priority+=.2*total_load[regions]/max(1.,regional.sum())
                    contact=ink
                    left=np.maximum(0,xx-1);right=np.minimum(nx,xx+cw+1)
                    bottom=np.maximum(0,yy-1);top=np.minimum(ny,yy+ch+1)
                    neighbours=contact[top,right]-contact[bottom,right]-contact[top,left]+contact[bottom,left]
                    priority-=.08*neighbours/(2*(cw+ch))
                    priority+=noise*.10
                    # Draw candidates from every region, so local repulsion can
                    # distinguish positions instead of examining one crowded patch.
                    shortlist=[]
                    for region in np.unique(regions):
                        ids=np.flatnonzero(regions==region)
                        shortlist.extend(ids[np.argsort(priority[ids],kind='stable')[:24]])
                    candidates=np.array(shortlist,dtype=int)
                    scores=priority[candidates].copy()
                    for ax,ay,ag in placed_centers:
                        if ag==group:
                            distance=(px[candidates]-ax)**2+(py[candidates]-ay)**2
                            scores+=.6*np.exp(-distance/(2*.13**2))
                    candidates=candidates[np.argsort(scores,kind='stable')]
                def try_at(k):
                    ix=int(xx[k]);iy=int(yy[k])
                    x=x0+(ix+cw/2)*dx;y=y0+(iy+ch/2)*dy
                    if not footprint_fits(sample,x,y,w,h,angle,s.check_step):return False
                    box=rectangle(x,y,w+margin,h+margin,angle)
                    if not placement_clear(box,occupied,s):return False
                    occupied.append(box)
                    filled[iy:iy+ch,ix:ix+cw]=True
                    record_center(x,y,idx)
                    if spreading:anchors.append(((ix+cw/2)/nx,(iy+ch/2)/ny))
                    records.append((x,y,idx,angle));counts[idx]+=1
                    return True
                for k in candidates:
                    if try_at(k):placed=True;break
                if not placed and len(xx)>len(candidates):
                    # Every shortlisted spot failed the exact check: try the other free spots too
                    # (otherwise a poster that fits somewhere is skipped, and the count jumps as settings change)
                    rest=np.setdiff1d(np.arange(len(xx)),np.asarray(candidates,dtype=int))
                    if not spreading:rest=rest[np.argsort(priority[rest],kind='stable')]
                    for k in rest[:600]:
                        if try_at(int(k)):placed=True;break
                if placed:added+=1;break
        if not added or not s.repeat:break
    return records

def random_records(s,catalog,sample,bounds,fixed,caps,counts,rects,margin):
    """Place the largest posters first, then spread each next size around the ones already placed.
    (If small ones scatter first, there is no room left for the big posters.)"""
    x0,x1,y0,y1=bounds;rng=random.Random(s.seed*7919+1);records=[];rects=BoxIndex(rects)
    order=sorted(range(len(catalog)),key=lambda i:-(catalog[i]['width']*catalog[i]['height']))
    placed=[(x,y,math.hypot(catalog[i]['width'],catalog[i]['height'])*s.scale*k/2) for x,y,i,_,k in fixed]
    def accept(x,y,idx):
        smp=sample(x,y)
        if smp is None:return False
        m,g,local=smp;dens=float(np.clip(m[0],0,1))
        if dens<.001 or rng.random()>dens:return False
        w=np.maximum(g[:3],0)[[2,1,0]];top=float(w.max())
        return top>1e-8 and rng.random()<=float(w[int(catalog[idx]['group'])])/top
    used=[0]
    def try_place(idx,tries):
        obj=catalog[idx];w=obj['width']*s.scale;h=obj['height']*s.scale;r=math.hypot(w,h)/2
        for _ in range(tries):
            used[0]+=1
            if placed and rng.random()<.7:   # Stick around already-placed posters so they spread outward
                cx,cy,cr=rng.choice(placed);d=cr+r*.75+margin+rng.uniform(0,.5*r);th=rng.uniform(0,2*math.pi)
                x=cx+d*math.cos(th);y=cy+d*math.sin(th)
            else:x=rng.uniform(x0,x1);y=rng.uniform(y0,y1)
            if not accept(x,y,idx):continue
            angle=inplane_angle(s,rng.uniform(-1,1))
            box=rectangle(x,y,w+margin,h+margin,angle)
            if not placement_clear(box,rects,s):continue
            if not footprint_fits(sample,x,y,w,h,angle,s.check_step):continue
            rects.append(box);records.append((x,y,idx,angle));counts[idx]+=1;placed.append((x,y,r));return True
        return False
    budget=min(80000,max(4000,s.count*400,len(catalog)*300))   # Only subtract attempts actually made
    while len(records)<s.count and used[0]<budget:
        progress=False
        for idx in order:   # Large -> small
            if len(records)>=s.count or used[0]>=budget:break
            if not quota_available(caps,counts,idx):continue
            n=600 if int(catalog[idx]['group'])==2 else 250
            if try_place(idx,n):progress=True
        if not progress or not s.repeat:break
    return records


GRID_LIMIT=1500   # Cap it, too many freezes Blender


def grid_records(s,catalog,sample,bounds,fixed,caps,counts):
    """Like a sticky-note board: overlap papers on a jittered grid with no gaps. Stacking order is shuffled."""
    x0,x1,y0,y1=bounds;rng=random.Random(s.seed*31+7)
    ws=sorted(o['width']*s.scale for o in catalog);hs=sorted(o['height']*s.scale for o in catalog)
    cw=ws[len(ws)//2];ch=hs[len(hs)//2]
    sx=max(cw*(1-s.grid_overlap),1e-4);sy=max(ch*(1-s.grid_overlap),1e-4)
    cells=[];j=0;y=y0+sy*.5
    while y<y1+sy*.5:
        off=sx*.5 if (s.grid_stagger and j%2) else 0.;x=x0+sx*.5-off
        while x<x1+sx*.5:
            cells.append((x+rng.uniform(-1,1)*s.grid_jitter*sx,y+rng.uniform(-1,1)*s.grid_jitter*sy));x+=sx
        y+=sy;j+=1
    rng.shuffle(cells)   # Placement order = stacking order where they overlap
    limit=min(GRID_LIMIT,len(cells) if s.count_auto and s.repeat else s.count)
    records=[]
    for x,y in cells:
        if len(records)>=limit:break
        if rng.random()>s.grid_fill:continue
        smp=sample(x,y)
        if smp is None or float(smp[0][0])<.01 or rng.random()>float(np.clip(smp[0][0],0,1)):continue
        avail=[i for i in range(len(catalog)) if quota_available(caps,counts,i)]
        if not avail:break
        low=min(counts[i] for i in avail);pool=[i for i in avail if counts[i]==low]   # Use evenly, then repeat
        for _ in range(3):
            idx=rng.choice(pool);o=catalog[idx];w=o['width']*s.scale;h=o['height']*s.scale
            angle=inplane_angle(s,rng.uniform(-1,1))
            if footprint_fits(sample,x,y,w,h,angle,s.check_step):
                records.append((x,y,idx,angle));counts[idx]+=1;break
    return records


def stack_target(o):
    """Stack target: the scatter area itself; picking its result (the visible posters) or its source face also resolves to the area."""
    if o is None:return None
    if getattr(o,'poster_scatter',None) is not None and o.poster_scatter.enabled:return o
    for a in bpy.data.objects:
        s=getattr(a,'poster_scatter',None)
        if s is None or not s.enabled:continue
        if o==s.output or o==a.parent or (o.parent==a):return a
    return None


def stack_on_changed(s,context):
    o=s.stack_on;t=stack_target(o)
    if o is not None and t is not None and t!=o:s.stack_on=t;return   # Dragging/eyedropping the result object still stores the area (called again)
    me=s.id_data
    if t is not None and t.poster_scatter.stack_on==me:t.poster_scatter.stack_on=None   # If already stacked in the reverse direction, undo that to remove the cycle
    if t is not None and not s.get('ps_was_stacked'):   # Existing scatter put on another one: start by filling the gaps (positions synced, nothing covered)
        s['ps_was_stacked']=True
        if s.stack_mode!='FILL':s.stack_mode='FILL'
    elif t is None and 'ps_was_stacked' in s:del s['ps_was_stacked']
    for a in [x for x in (t,me) if x is not None]:   # Re-scatter immediately
        try:rebuild(a);SIGNATURES[a.as_pointer()]=signature(a)
        except Exception as exc:print('poster_scatter stack',exc)


def stack_chain(area):
    """Every layer under this area, nearest first (layer 3 -> layer 2 -> layer 1). Stops at loops."""
    out=[];seen={area.as_pointer()};b=area.poster_scatter.stack_on
    while b is not None and getattr(b,'poster_scatter',None) and b.poster_scatter.enabled and b.as_pointer() not in seen:
        out.append(b);seen.add(b.as_pointer());b=b.poster_scatter.stack_on
    return out


def stack_poll(s,o):
    t=stack_target(o);me=s.id_data
    return t is not None and t!=me and me not in stack_chain(t)   # No loops (A on B on A)


def stack_mode_changed(s,context):
    try:rebuild(s.id_data);SIGNATURES[s.id_data.as_pointer()]=signature(s.id_data)
    except Exception as exc:print('poster_scatter stack mode',exc)


def stack_top(area):
    """The highest layer resting on this area (or the area itself): a new layer goes on top of it."""
    best=area;depth=0
    for o in bpy.context.scene.objects:
        if getattr(o,'poster_scatter',None) and o.poster_scatter.enabled and o!=area:
            ch=stack_chain(o)
            if area in ch and ch.index(area)+1>depth:best=o;depth=ch.index(area)+1
    return best


def base_surfaces(area):
    """Stack on top: bring the real (bent) papers of every layer below into this area's coordinates and stack on top of them."""
    s=area.poster_scatter
    if (s.stack_mode=='FILL' and not s.allow_overlap) or area_flat(area.data) is not None:return []   # Fill mode avoids them (unless overlap is allowed: then the overlapping parts must rest on top too); curved areas are not supported yet
    out=[]
    for b in stack_chain(area):out+=area_papers(b,area)
    return out


def lower_footprints(area,pad=0.):
    """Fill Empty Space: turned rectangles (this area's coordinates) holding each paper of every layer below."""
    s=area.poster_scatter
    if s.stack_mode!='FILL' or area_flat(area.data) is not None:return []
    out=[]
    for b in stack_chain(area):
        bs=b.poster_scatter
        if not bs.output or not bs.render_cache:continue
        me=bs.output.data;attrs=[me.attributes.get(n) for n in ('poster_index','poster_rotation','poster_scale')]
        if any(a is None or len(a.data)!=len(me.vertices) for a in attrs):continue
        bent=sorted(bs.render_cache.objects,key=lambda o:o.name)
        ow=bs.output.matrix_world if bs.output.parent!=b else b.matrix_world@bs.output.matrix_parent_inverse@bs.output.matrix_basis
        M=area.matrix_world.inverted()@ow
        for i,v in enumerate(me.vertices):
            j=attrs[0].data[i].value
            if not 0<=j<len(bent):continue
            rot=Euler(tuple(attrs[1].data[i].vector),'XYZ').to_matrix();k=attrs[2].data[i].value
            P=np.array([(M@(v.co+rot@(w.co*k)))[:2] for w in bent[j].data.vertices],np.float64)
            ax=(M.to_3x3()@rot)@Vector((1,0,0));ang=math.atan2(ax.y,ax.x)
            out.append(footprint(P,float(P[:,0].mean()),float(P[:,1].mean()),ang,pad*.5+1e-6))
    return out


def pressers(area):
    """Other areas stacked on top of this one, at any depth (their papers press this area's papers)."""
    if area_flat(area.data) is not None:return []
    return [o for o in bpy.context.scene.objects if o!=area and getattr(o,'poster_scatter',None) and o.poster_scatter.enabled
            and o.poster_scatter.stack_mode=='TOP' and area in stack_chain(o)]


def area_papers(b,area):
    """Papers of area b in the coordinates of area: [rectangle, None, 0, vertices, triangles]"""
    bs=b.poster_scatter
    if not bs.output or not bs.render_cache:return []
    me=bs.output.data;attrs=[me.attributes.get(n) for n in ('poster_index','poster_rotation','poster_scale')]
    if any(a is None or len(a.data)!=len(me.vertices) for a in attrs):return []
    bent=sorted(bs.render_cache.objects,key=lambda o:o.name)
    ow=bs.output.matrix_world if bs.output.parent!=b else b.matrix_world@bs.output.matrix_parent_inverse@bs.output.matrix_basis
    M=area.matrix_world.inverted()@ow;out=[];shared={}
    for i,v in enumerate(me.vertices):
        j=attrs[0].data[i].value
        if not 0<=j<len(bent):continue
        rot=Euler(tuple(attrs[1].data[i].vector),'XYZ').to_matrix();k=attrs[2].data[i].value
        pts=[M@(v.co+rot@(w.co*k)) for w in bent[j].data.vertices]
        lx=min(p.x for p in pts);hx=max(p.x for p in pts);ly=min(p.y for p in pts);hy=max(p.y for p in pts)
        box=[Vector((lx,ly)),Vector((hx,ly)),Vector((hx,hy)),Vector((lx,hy))]
        out.append([box,None,0.,pts,render_tris(bent[j].data,shared)])
    return out


PLACE_CACHE={}


RAIL='ps_rail'   # Edge attribute marking which edges of a rail mesh are used
RAIL_LIMIT=1500
RAIL_MAX_EDGES=20000   # Safety: more edges than this is not a rail (a thick tube, a whole model)
RAIL_MAX_PIECES=64     # Safety: a rail split into more separate pieces than this is almost surely a mesh surface, not a line


def simplify_polyline(P,tol):
    """Douglas-Peucker in 3D: drops points closer than tol to the line between kept points
    (tiny wraps around a nail, dense resampling), keeping the overall shape."""
    n=len(P)
    if n<3:return P
    keep=np.zeros(n,bool);keep[0]=keep[-1]=True;stack=[(0,n-1)]
    while stack:
        a,b=stack.pop()
        if b-a<2:continue
        A,B=P[a],P[b];AB=B-A;L=float(np.dot(AB,AB))
        seg=P[a+1:b]
        if L<1e-18:d=np.linalg.norm(seg-A,axis=1)
        else:
            t=np.clip((seg-A)@AB/L,0.,1.);d=np.linalg.norm(seg-(A+t[:,None]*AB),axis=1)
        i=int(np.argmax(d))
        if d[i]>tol:m=a+1+i;keep[m]=True;stack+=[(a,m),(m,b)]
    return P[keep]


def curve_centerline(o):
    """A curve's center line without bevel / extrude (a thick rope would otherwise become a tube mesh
    with thousands of edges), simplified to ~3 mm: (points (n,3) world, edges (m,2)), or None."""
    from mathutils.geometry import interpolate_bezier
    M=o.matrix_world;Vs=[];Es=[]
    for sp in o.data.splines:
        if sp.type=='BEZIER':
            bp=list(sp.bezier_points);segs=len(bp) if sp.use_cyclic_u else len(bp)-1;pts=[]
            res=max(2,sp.resolution_u)
            for i in range(segs):
                a,b=bp[i],bp[(i+1)%len(bp)]
                seg=interpolate_bezier(a.co,a.handle_right,b.handle_left,b.co,res+1)
                pts+=list(seg[:-1]) if i<segs-1 or sp.use_cyclic_u else list(seg)
        else:pts=[Vector(p.co[:3]) for p in sp.points]
        if len(pts)<2:continue
        P=np.array([tuple(M@Vector(p)) for p in pts],np.float64)
        P=simplify_polyline(P,.003)
        base=sum(len(v) for v in Vs);n=len(P)
        Vs.append(P);Es+=[(base+i,base+i+1) for i in range(n-1)]
        if sp.use_cyclic_u and n>2:Es.append((base+n-1,base))
    if not Vs or not Es:return None
    if len(Es)>RAIL_MAX_EDGES:
        raise ValueError('"%s" is too detailed for a rail (%d segments even after simplifying). Use a simpler curve.'%(o.name,len(Es)))
    return np.concatenate(Vs),np.array(Es,np.int64)


def rail_guard(o,V,E):
    """Protects against rails that would freeze Blender (thousands of edges / pieces, e.g. a beveled or solid
    object picked as the rail): clear error instead of a hang, and dense lines are simplified to ~3 mm."""
    if len(E)>RAIL_MAX_EDGES:
        raise ValueError('"%s" has %d edges, too many for a rail. Use a thin curve or line, or in Edit Mode select only the edges to hang from.'%(o.name,len(E)))
    chains=chain_edges(E)
    if len(chains)>RAIL_MAX_PIECES:
        raise ValueError('"%s" splits into %d separate pieces, which looks like a surface rather than a line. Use a thin curve, or select only the hanging edges in Edit Mode.'%(o.name,len(chains)))
    Vs=[];Es=[]
    for path,closed in chains:   # Thin out dense lines; tiny wiggles (wraps, noise) disappear
        P=V[path]
        if len(P)>2 and not closed:P=simplify_polyline(P,.003)
        base=sum(len(v) for v in Vs);n=len(P)
        Vs.append(P);Es+=[(base+i,base+i+1) for i in range(n-1)]
        if closed and n>2:Es.append((base+n-1,base))
    if not Vs or not Es:return None
    return np.concatenate(Vs),np.array(Es,np.int64)


def rail_geometry(o):
    """A curve's evaluated line, or a mesh's edges (only the marked ones, if any), in world space: (points (n,3), edges (m,2)), or None."""
    if o is None or o.type not in {'CURVE','MESH'}:return None
    if o.type=='CURVE' and not o.modifiers:return curve_centerline(o)
    dg=bpy.context.evaluated_depsgraph_get();ev=o.evaluated_get(dg)
    try:me=ev.to_mesh()
    except RuntimeError:return None
    try:
        if me is None or not len(me.edges):return None
        V=np.empty(len(me.vertices)*3,np.float64);me.vertices.foreach_get('co',V);V=V.reshape(-1,3)
        E=np.empty(len(me.edges)*2,np.int64);me.edges.foreach_get('vertices',E);E=E.reshape(-1,2)
        if o.type=='MESH':
            a=o.data.attributes.get(RAIL)   # Read from the original mesh (modifiers may drop attributes)
            if a is not None and a.domain=='EDGE' and a.data_type=='BOOLEAN' and len(o.data.edges)==len(me.edges):
                mark=np.zeros(len(a.data),bool);a.data.foreach_get('value',mark)
                if mark.any():E=E[mark]
        M=np.array(ev.matrix_world,np.float64)
        return rail_guard(o,V@M[:3,:3].T+M[:3,3],E)
    finally:ev.to_mesh_clear()


def rail_raw(area):
    """Rail geometry in the area's local space, or None."""
    g=rail_geometry(area.poster_scatter.rail_object)
    if g is None:return None
    M=np.array(area.matrix_world.inverted(),np.float64)
    return g[0]@M[:3,:3].T+M[:3,3],g[1]

RAIL_KEYS={}


def rail_fingerprint(area):
    """Cheap check for rail changes (no evaluation): transforms plus raw curve points or mesh vertices.
    Rails with modifiers return None, so they are always fully evaluated."""
    o=area.poster_scatter.rail_object
    if o is None or o.modifiers:return None
    h=hashlib.blake2b(digest_size=12);h.update(np.array(o.matrix_world,np.float32).tobytes());h.update(np.array(area.matrix_world,np.float32).tobytes())
    d=o.data;h.update(str((o.name,d.name,o.mode)).encode())
    if o.type=='CURVE':
        h.update(str((d.resolution_u,d.dimensions,d.twist_mode,len(d.splines))).encode())
        for sp in d.splines:
            h.update(str((sp.type,sp.use_cyclic_u,sp.resolution_u,len(sp.points),len(sp.bezier_points))).encode())
            if sp.type=='BEZIER':
                for k in ('co','handle_left','handle_right'):
                    b=np.empty(len(sp.bezier_points)*3,np.float32);sp.bezier_points.foreach_get(k,b);h.update(b.tobytes())
            else:
                b=np.empty(len(sp.points)*4,np.float32);sp.points.foreach_get('co',b);h.update(b.tobytes())
    elif o.type=='MESH':
        b=np.empty(len(d.vertices)*3,np.float32);d.vertices.foreach_get('co',b);h.update(b.tobytes())
        e=np.empty(len(d.edges)*2,np.int32);d.edges.foreach_get('vertices',e);h.update(e.tobytes())
        a=d.attributes.get(RAIL)
        if a is not None and a.domain=='EDGE' and a.data_type=='BOOLEAN':
            m=np.zeros(len(a.data),bool);a.data.foreach_get('value',m);h.update(m.tobytes())
    return h.digest()


def rail_key(area):
    """Everything about the rail that moves papers: settings plus the rail's shape and placement."""
    s=area.poster_scatter;h=hashlib.blake2b(digest_size=12)
    fp=rail_fingerprint(area);hit=RAIL_KEYS.get(area.as_pointer())
    if fp is not None and hit and hit[0]==fp:geo=hit[1]   # Unchanged rail: skip evaluating it
    else:
        raw=rail_raw(area);g=hashlib.blake2b(digest_size=12)
        if raw is not None:g.update(np.round(raw[0],6).astype(np.float32).tobytes());g.update(raw[1].tobytes())
        geo=g.digest()
        if fp is not None:RAIL_KEYS[area.as_pointer()]=(fp,geo)
    h.update(geo)
    h.update(str((s.rail_object.name if s.rail_object else '',s.rail_hang,round(s.rail_overlap,5),round(s.rail_jitter,5),round(s.rail_drop,6),
                  round(s.rail_drop_random,6),round(s.rail_swing,6),s.rail_order,round(s.rail_slide,6),s.rail_wrap,s.rail_reverse,round(s.rail_margin,5),s.rail_pick)).encode())
    return h.digest()


def chain_edges(E):
    """Join loose edges into ordered chains: [(vertex indices, closed)]. Branch points split chains."""
    adj={}
    for i,(a,b) in enumerate(E.tolist()):
        if a==b:continue
        adj.setdefault(a,[]).append((b,i));adj.setdefault(b,[]).append((a,i))
    used=set();chains=[]
    def walk(v,w,ei):
        path=[v,w];used.add(ei);cur=w
        while len(adj[cur])==2:
            nxt=[(x,e) for x,e in adj[cur] if e not in used]
            if not nxt:break
            x,e=nxt[0];used.add(e);path.append(x);cur=x
        return path
    for v in sorted(adj):   # Open chains start at ends and branch points
        if len(adj[v])==2:continue
        for w,ei in adj[v]:
            if ei not in used:chains.append((walk(v,w,ei),False))
    for v in sorted(adj):   # Whatever is left are closed loops
        for w,ei in adj[v]:
            if ei not in used:
                path=walk(v,w,ei);closed=len(path)>2 and path[-1]==path[0]
                chains.append((path[:-1] if closed else path,closed))
    return chains


def trim_polyline(P,m):
    """Cut length m off both ends of an open 2D polyline (nothing left if it is shorter than 2m)."""
    seg=np.hypot(*np.diff(P,axis=0).T);cum=np.concatenate([[0.],np.cumsum(seg)]);L=cum[-1]
    if L<=2*m+1e-6:return P[:0]
    def at(d):
        i=int(np.clip(np.searchsorted(cum,d)-1,0,len(seg)-1));t=(d-cum[i])/max(seg[i],1e-12);return P[i]+(P[i+1]-P[i])*t
    keep=(cum>m)&(cum<L-m)
    return np.vstack([at(m)[None],P[keep],at(L-m)[None]])


def rail_polylines(area):
    """Rail as 2D polylines in layout coordinates: [(points (n,2), closed)]."""
    raw=rail_raw(area)
    if raw is None:return []
    V,E=raw;s=area.poster_scatter
    if s.curved:   # Project onto the curved surface, then into its unfolded plane
        smap=SurfaceMap(area.data);F=[]
        for p in V:
            hit=smap.surface.find_nearest(Vector(p))
            if hit[2] is None:F.append((p[0],p[1]));continue
            f=smap.to_flat(hit[2],hit[0]);F.append((f.x,f.y))
        F=np.array(F,np.float64)
    else:F=V[:,:2].copy()
    out=[]
    for path,closed in chain_edges(E):
        P=F[path]
        if len(P)<2:continue
        keep=np.concatenate([[True],np.hypot(*np.diff(P,axis=0).T)>1e-9]);P=P[keep]
        if len(P)<2:continue
        if not closed and s.rail_margin>0:P=trim_polyline(P,s.rail_margin)   # keep papers off the very ends (nails, hooks)
        if len(P)<2:continue
        if not closed and P[0,0]>P[-1,0]:P=P[::-1]   # Open rails run left to right by default
        if s.rail_reverse:P=P[::-1]
        out.append((P,closed))
    return out


RAIL_PIVOT_SLACK=.002   # how far a hanging paper's clip point may move off the line to clear the paper under it (m)


def rail_records(s,catalog,sample,polys,caps,counts):
    """Hang papers along a rail, top edge on the line, spaced by paper width with some overlap,
    like order tickets on a kitchen rail or notes clipped to a string."""
    rng=random.Random(s.seed*53+11);records=[]
    limit=RAIL_LIMIT if (s.count_auto and s.repeat) else min(RAIL_LIMIT,s.count)
    for P,closed in polys:
        if len(records)>=limit:break
        if closed:P=np.vstack([P,P[:1]])
        seg=np.diff(P,axis=0);segL=np.hypot(seg[:,0],seg[:,1])
        cum=np.concatenate([[0.],np.cumsum(segL)]);total=float(cum[-1])
        if total<1e-6:continue
        d=0.
        while d<total-1e-9 and len(records)<limit:
            avail=[i for i in range(len(catalog)) if quota_available(caps,counts,i)]
            if not avail:break
            low=min(counts[i] for i in avail);pool=[i for i in avail if counts[i]==low]   # Use evenly, then repeat
            idx=min(pool) if s.rail_pick=='NUMBER' else rng.choice(pool);o=catalog[idx];w=o['width']*s.scale;h=o['height']*s.scale   # By Number: 1, 2, 3... (then again)
            r_gap,r_swing,r_drop,r_rot=rng.uniform(-1,1),rng.uniform(-1,1),rng.uniform(-1,1),rng.uniform(-1,1)
            center=d+w*.5;d+=max(w*(1-s.rail_overlap)*(1+r_gap*s.rail_jitter*.5),w*.05)
            if not closed and center>total:break
            dd=center+s.rail_slide   # Slide moves every paper along the rail (keyframe it for a conveyor)
            if closed or s.rail_wrap:dd%=total
            elif dd<0 or dd>total:continue
            i=min(max(int(np.searchsorted(cum,dd,side='right'))-1,0),len(seg)-1)
            Li=max(float(segL[i]),1e-12);t=(dd-cum[i])/Li
            ax,ay=P[i]+seg[i]*t;tx,ty=seg[i]/Li
            if s.rail_hang=='GRAVITY':dx,dy=0.,-1.
            else:   # Perpendicular to the rail, on its lower side
                dx,dy=ty,-tx
                if dy>0 or (abs(dy)<1e-9 and dx<0):dx,dy=-dx,-dy
            angle=math.atan2(dx,-dy)+r_swing*s.rail_swing+inplane_angle(s,r_rot)   # Swing and the surface spin both turn it around the clip point
            drop=s.rail_drop+r_drop*s.rail_drop_random
            ux,uy=-math.sin(angle),math.cos(angle)
            cx=float(ax-ux*(h*.5+drop));cy=float(ay-uy*(h*.5+drop))
            smp=sample(cx,cy)
            if smp is not None and float(smp[0][0])<.01:continue   # Painted out
            records.append((cx,cy,idx,angle));counts[idx]+=1
    if s.rail_order=='BACKWARD':records.reverse()
    elif s.rail_order=='RANDOM':rng.shuffle(records)
    return records


def placement_key(area,catalog,fixed):
    """Key built only from values that affect poster positions (press, lift, tilt and offset are excluded)."""
    s=area.poster_scatter;h=hashlib.blake2b(digest_size=16)
    for name in (MASK,SEED):h.update(colors(area.data,name).tobytes())
    h.update(np.array([(v.co.x,v.co.y,v.co.z) for v in area.data.vertices[:256]],np.float32).tobytes());h.update(str(len(area.data.vertices)).encode())
    ensure_repeat_ranges(s)
    h.update(str((s.layout,s.count,s.seed,s.gap,(s.rot_x_on,s.rot_y_on,s.rot_z_on,tuple(round(getattr(s,'rot_%s_%s'%(ax,k)),6) for ax in 'xyz' for k in ('angle','rand'))),s.scale,s.repeat,s.repeat_limited,[(r.upper,r.limit) for r in s.repeat_ranges],
                  s.grid_overlap,s.grid_jitter,s.grid_fill,s.grid_stagger,s.allow_overlap,s.overlap_ratio,getattr(s,'check_step',0),
                  topology_signature(s),[(o.name,o.get('width'),o.get('height'),o.get('group')) for o in catalog],fixed)).encode())
    for k in ('count_auto','source_count'):h.update(str(getattr(s,k,None)).encode())
    if s.layout=='RAIL':h.update(rail_key(area))
    return h.digest()


TOPO={}   # Per rebuild: facts that depend only on how a paper's faces connect, shared by papers cut from the same source


def render_tris(me,shared):
    """The triangles Blender really draws for this mesh (a bent quad may be split along either diagonal,
    and the two splits can sit millimetres apart). Equal lists are shared so their topology is worked out once."""
    me.calc_loop_triangles();T=np.empty(len(me.loop_triangles)*3,np.int64);me.loop_triangles.foreach_get('vertices',T)
    T=T.reshape(-1,3);key=T.tobytes();hit=shared.get(key)
    if hit is None:shared[key]=hit=T
    return hit


def topology_info(F):
    """Edges, outline, creases and triangle splits of a face list (or a triangle array). Cached per list object."""
    hit=TOPO.get(id(F))
    if hit is not None and hit['F'] is F:return hit
    if isinstance(F,np.ndarray):groups=[(3,F)] if len(F) else []
    else:
        groups={}
        for f in F:groups.setdefault(len(f),[]).append(f)
        groups=[(m,np.array(fs,np.int64)) for m,fs in groups.items() if m>=3]
    def cat(parts,w):return np.concatenate(parts) if parts else np.zeros((0,w),np.int64)
    sides=np.sort(cat([np.stack([arr[:,i],arr[:,(i+1)%m]],1) for m,arr in groups for i in range(m)],2),1)
    edges,cnt=np.unique(sides,axis=0,return_counts=True)
    outline=edges[cnt==1]
    creases=np.unique(np.sort(cat([np.stack([arr[:,i],arr[:,j]],1) for m,arr in groups for i in range(m) for j in range(i+1,m)],2),1),axis=0)
    tris=cat([np.stack([arr[:,0],arr[:,i],arr[:,i+1]],1) for m,arr in groups for i in range(1,m-1)],3)
    tris2=cat([np.stack([arr[:,1],arr[:,(i+1)%m],arr[:,(i+2)%m]],1) for m,arr in groups for i in range(1,m-1)],3)
    loop=None
    if len(outline):
        ch=chain_edges(outline)
        if len(ch)==1 and ch[0][1]:loop=np.array(ch[0][0],np.int64)   # One closed outline: usable for fast inside tests
    info={'F':F,'groups':groups,'edges':edges,'outline':outline,'outline_verts':np.unique(outline),'creases':creases,'tris':tris,'tris2':tris2,'loop':loop,
          'mixed':any(m>3 for m,_ in groups)}
    TOPO[id(F)]=info;return info


def paper_info(entry):
    """Per placed paper, worked out once per rebuild and shared by every paper that overlaps it:
    its topology facts plus face boxes with their height range."""
    while len(entry)<7:entry.append(None)
    if len(entry)>7:return entry[7]
    P=entry[3];topo=topology_info(entry[4])
    parts=[]
    for m,arr in topo['groups']:
        Q=P[arr];parts.append(np.column_stack([Q[...,0].min(1),Q[...,1].min(1),Q[...,0].max(1),Q[...,1].max(1),Q[...,2].min(1),Q[...,2].max(1)]))
    info=dict(topo);info['fbox']=np.concatenate(parts) if parts else np.zeros((0,6))
    Q=P[topo['tris']];info['tbox']=np.column_stack([Q[...,0].min(1),Q[...,1].min(1),Q[...,0].max(1),Q[...,1].max(1)]) if len(Q) else np.zeros((0,4))
    entry.append(info);return info


def flat_height(info,ax0,ax1,ay0,ay1):
    """Height of the paper inside the box if it is one flat sheet there (pressed papers usually are), else None."""
    fb=info['fbox'];reg=(fb[:,0]<=ax1)&(fb[:,2]>=ax0)&(fb[:,1]<=ay1)&(fb[:,3]>=ay0)
    if not reg.any():return None
    lo=float(fb[reg,4].min())
    return lo if float(fb[reg,5].max())-lo<1e-7 else None


def points_in_loop(Q,L,eps=1e-7):
    """Even-odd test: which XY points lie inside the closed outline L (points on the outline count as inside)."""
    if not len(Q):return np.zeros(0,bool)
    x=Q[:,0][:,None];y=Q[:,1][:,None];x1=L[:,0][None];y1=L[:,1][None];x2=np.roll(L[:,0],-1)[None];y2=np.roll(L[:,1],-1)[None]
    cross=(y1>y)!=(y2>y)
    with np.errstate(divide='ignore',invalid='ignore'):xi=x1+(y-y1)*(x2-x1)/(y2-y1)
    inside=((cross&(x<xi)).sum(1)%2)==1
    dxl=x2-x1;dyl=y2-y1;dd=dxl*dxl+dyl*dyl;t=np.clip(((x-x1)*dxl+(y-y1)*dyl)/np.where(dd>0,dd,1.),0.,1.)
    on=((x-x1-t*dxl)**2+(y-y1-t*dyl)**2).min(1)<=eps*eps   # Same as a ray from above, which counts edge hits
    return inside|on


def layer_z(P,T,S,top):
    """Height of a paper (points P, triangles T) at the XY points S: its top layer (top=True) or its
    bottom layer. NaN where the paper is not there."""
    A=P[T[:,0]];B=P[T[:,1]];C=P[T[:,2]]
    den=(B[:,1]-C[:,1])*(A[:,0]-C[:,0])+(C[:,0]-B[:,0])*(A[:,1]-C[:,1]);ok=np.abs(den)>1e-18;den=np.where(ok,den,1.)
    dx=S[:,None,0]-C[None,:,0];dy=S[:,None,1]-C[None,:,1]
    l1=((B[:,1]-C[:,1])[None]*dx+(C[:,0]-B[:,0])[None]*dy)/den[None];l2=((C[:,1]-A[:,1])[None]*dx+(A[:,0]-C[:,0])[None]*dy)/den[None];l3=1.-l1-l2
    z=l1*A[None,:,2]+l2*B[None,:,2]+l3*C[None,:,2]
    z=np.where(ok[None]&(l1>=-1e-9)&(l2>=-1e-9)&(l3>=-1e-9),z,-np.inf if top else np.inf)
    r=z.max(1) if top else z.min(1)
    return np.where(np.isfinite(r),r,np.nan)


def rise_over(pts,FA,P,FB,box):
    """How far paper A (pts, triangles FA) must rise as a whole to clear paper B (P, FB) where they overlap.
    Two flat-faced papers come closest only at a vertex of either one or where their edges cross,
    so those points are all that is checked. None when they do not overlap."""
    ax0,ax1,ay0,ay1=box
    def near_tris(Q,T):
        a=Q[T[:,0],:2];b=Q[T[:,1],:2];c=Q[T[:,2],:2];lo=np.minimum(np.minimum(a,b),c);hi=np.maximum(np.maximum(a,b),c)
        return T[(lo[:,0]<=ax1)&(hi[:,0]>=ax0)&(lo[:,1]<=ay1)&(hi[:,1]>=ay0)]
    TA=near_tris(pts,FA);TB=near_tris(P,FB)
    if not len(TA) or not len(TB):return None
    def edges(T):return np.unique(np.sort(np.vstack([T[:,[0,1]],T[:,[1,2]],T[:,[2,0]]]),1),axis=0)
    EA=edges(TA);EB=edges(TB)
    V=np.vstack([pts[np.unique(TA),:2],P[np.unique(TB),:2]])
    S=[V[(V[:,0]>=ax0)&(V[:,0]<=ax1)&(V[:,1]>=ay0)&(V[:,1]<=ay1)]]
    P1=P[EB[:,0],:2];D1=P[EB[:,1],:2]-P1;Q1=pts[EA[:,0],:2];D2=pts[EA[:,1],:2]-Q1
    den=D1[:,None,0]*D2[None,:,1]-D1[:,None,1]*D2[None,:,0];W=Q1[None,:,:]-P1[:,None,:]
    with np.errstate(divide='ignore',invalid='ignore'):
        t=(W[...,0]*D2[None,:,1]-W[...,1]*D2[None,:,0])/den;u=(W[...,0]*D1[:,None,1]-W[...,1]*D1[:,None,0])/den
        ok=(np.abs(den)>1e-14)&(t>=0)&(t<=1)&(u>=0)&(u<=1)
    li,ti=np.nonzero(ok);S.append(P1[li]+t[li,ti][:,None]*D1[li]);S=np.vstack(S)
    if not len(S):return None
    d=layer_z(P,TB,S,True)-layer_z(pts,TA,S,False);d=d[np.isfinite(d)]
    return float(d.max()) if len(d) else None


def conform_push(s,me,pts,depth,box,bb,near,faces,pedges=None):
    """Rest on Papers Below: per-vertex rise so a paper lies on what is directly beneath it.
    Parts over bare wall stay down, parts over a lower paper rise by its height plus the gap,
    and the rise spreads a little (paper stiffness) so the paper ramps over the lower edge.
    Returns the rise per vertex along the wall normal, or None when nothing is below."""
    # All heights are read straight off the drawn triangles (no rays): exact, and nothing slips past a paper's rim.
    nv=len(pts);gap=s.overlap_depth;over=[]
    for entry in near:
        if not aabb_hit(bb,entry[5]) or separated(box,entry[0]):continue
        over.append(entry)
    if not over:return None
    raw=np.zeros(nv,np.float64);absz=pts[:,2]+depth
    for entry in over:   # 1) Each vertex: height of the papers directly below it
        pd=entry[2];e5=entry[5]
        sel=np.nonzero((pts[:,0]>=e5[0])&(pts[:,0]<=e5[2])&(pts[:,1]>=e5[1])&(pts[:,1]<=e5[3]))[0]
        if not len(sel) or not len(entry[4]):continue
        info=paper_info(entry);ax0=max(bb[0],e5[0]);ax1=min(bb[2],e5[2]);ay0=max(bb[1],e5[1]);ay1=min(bb[3],e5[3])
        h=flat_height(info,ax0,ax1,ay0,ay1) if info['loop'] is not None else None
        if h is not None:   # Flat sheet below with one outline: one inside test for all vertices
            ins=points_in_loop(pts[sel,:2],entry[3][info['loop'],:2])
            if ins.any():np.maximum.at(raw,sel[ins],pd+h+gap-absz[sel[ins]])
            continue
        tb=info['tbox'];T=info['tris'][(tb[:,0]<=ax1)&(tb[:,2]>=ax0)&(tb[:,1]<=ay1)&(tb[:,3]>=ay0)]
        if not len(T):continue
        zb=layer_z(entry[3],T,pts[sel,:2],True);ok=np.isfinite(zb)   # Top of the paper below at each vertex
        if ok.any():np.maximum.at(raw,sel[ok],pd+zb[ok]+gap-absz[sel[ok]])
    topo=topology_info(faces);E=topo['edges'] if pedges is None else pedges   # Stiffness follows the paper's own mesh edges
    deg=np.maximum(np.bincount(E.ravel(),minlength=nv)[:nv].astype(np.float64),1.)
    steps=int(round(max(0.,min(1.,s.grid_stiffness))*8))
    def spread(r):   # 2) Stiffness: the rise fades out into the rest of the paper, never below what is required
        q=r.copy()
        for _ in range(steps if len(E) else 0):
            acc=np.zeros(nv);np.add.at(acc,E[:,0],q[E[:,1]]);np.add.at(acc,E[:,1],q[E[:,0]])
            q=np.maximum(r,.85*.5*(q+acc/deg))
        return q
    tris=topo['tris'];tris2=topo['tris2'] if topo['mixed'] else None   # Drawn triangles; plain faces: both ways a quad may split
    TE_all=topo['creases']   # This paper's triangle edges
    # 3) Between vertices. Two piecewise-flat surfaces are furthest apart (or deepest through each other)
    # only at a vertex of either one or where their edges cross, so those points are all we check.
    # Where the paper below is one flat sheet (pressed papers usually are), only its outline matters.
    # XY never changes (the paper only rises), so points and lower-paper heights are found once.
    def in_box(A,B,x0_,x1_,y0_,y1_):
        return (np.minimum(A[:,0],B[:,0])<=x1_)&(np.maximum(A[:,0],B[:,0])>=x0_)&(np.minimum(A[:,1],B[:,1])<=y1_)&(np.maximum(A[:,1],B[:,1])>=y0_)
    pre=[]
    for entry in over:
        pd=entry[2];e5=entry[5];P=entry[3]
        ax0=max(bb[0],e5[0]);ax1=min(bb[2],e5[2]);ay0=max(bb[1],e5[1]);ay1=min(bb[3],e5[3])
        if ax0>ax1 or ay0>ay1 or not len(entry[4]):continue
        info=paper_info(entry);fb=info['fbox']
        reg=(fb[:,0]<=ax1)&(fb[:,2]>=ax0)&(fb[:,1]<=ay1)&(fb[:,3]>=ay0)
        if not reg.any():continue
        h=flat_height(info,ax0,ax1,ay0,ay1);flat=h is not None
        LE=info['outline'] if flat else info['creases'];VI=info['outline_verts'] if flat else np.arange(len(P))
        # Every check point sits on a vertex or an edge of the lower paper, so its height there is read
        # straight off that vertex or edge: exact, and no ray can slip past the paper's rim.
        V3=P[VI];V3=V3[(V3[:,0]>=ax0)&(V3[:,0]<=ax1)&(V3[:,1]>=ay0)&(V3[:,1]<=ay1)];samples=V3[:,:2];zs=V3[:,2]
        LE=LE[in_box(P[LE[:,0]],P[LE[:,1]],ax0,ax1,ay0,ay1)] if len(LE) else LE
        TE=TE_all[in_box(pts[TE_all[:,0]],pts[TE_all[:,1]],ax0,ax1,ay0,ay1)] if len(TE_all) else TE_all
        if len(LE) and len(TE):   # Where this paper's edges cross the lower paper's edges
            P1=P[LE[:,0],:2];D1=P[LE[:,1],:2]-P1;Q1=pts[TE[:,0],:2];D2=pts[TE[:,1],:2]-Q1
            den=D1[:,None,0]*D2[None,:,1]-D1[:,None,1]*D2[None,:,0];W=Q1[None,:,:]-P1[:,None,:]
            with np.errstate(divide='ignore',invalid='ignore'):
                t=(W[...,0]*D2[None,:,1]-W[...,1]*D2[None,:,0])/den;u=(W[...,0]*D1[:,None,1]-W[...,1]*D1[:,None,0])/den
                ok=(np.abs(den)>1e-14)&(t>=0)&(t<=1)&(u>=0)&(u<=1)
            li,ti=np.nonzero(ok);tt=t[li,ti]
            samples=np.vstack([samples,P1[li]+tt[:,None]*D1[li]])
            zs=np.concatenate([zs,P[LE[li,0],2]+tt*(P[LE[li,1],2]-P[LE[li,0],2])])
        if not len(samples):continue
        pre.append(np.column_stack([samples,np.full(len(samples),pd+h+gap) if flat else pd+zs+gap]))
    S=np.vstack(pre) if pre else np.zeros((0,3))   # (x, y, height the paper must clear)
    push=spread(raw)
    if not len(S):return push
    # Which triangle of this paper each check point lies in. Found once (XY is fixed);
    # each pass then only re-reads the vertex heights of those pairs.
    def locate(T):
        T=np.asarray(T,np.int64).reshape(-1,3);A=pts[T[:,0],:2];B=pts[T[:,1],:2];C=pts[T[:,2],:2]
        lo=np.minimum(np.minimum(A,B),C);hi=np.maximum(np.maximum(A,B),C)
        keep=(lo[:,0]<=S[:,0].max())&(hi[:,0]>=S[:,0].min())&(lo[:,1]<=S[:,1].max())&(hi[:,1]>=S[:,1].min())
        T=T[keep];A=A[keep];B=B[keep];C=C[keep]
        den=(B[:,1]-C[:,1])*(A[:,0]-C[:,0])+(C[:,0]-B[:,0])*(A[:,1]-C[:,1]);ok=np.abs(den)>1e-18;den=np.where(ok,den,1.)
        dx=S[:,None,0]-C[None,:,0];dy=S[:,None,1]-C[None,:,1]
        l1=((B[:,1]-C[:,1])[None]*dx+(C[:,0]-B[:,0])[None]*dy)/den[None];l2=((C[:,1]-A[:,1])[None]*dx+(A[:,0]-C[:,0])[None]*dy)/den[None]
        si,ti=np.nonzero(ok[None]&(l1>=-1e-9)&(l2>=-1e-9)&(l1+l2<=1+1e-9))
        return T[ti],si,np.stack([l1[si,ti],l2[si,ti],1.-l1[si,ti]-l2[si,ti]],-1)
    splits=[locate(tris)]+([locate(tris2)] if tris2 is not None else [])
    for _ in range(8):
        need_r=raw.copy();bad=False
        for V,si,Wp in splits:
            if not len(si):continue
            zp=(Wp*(push[V]+pts[V,2])).sum(-1)+depth   # Height of each triangle's plane under its points
            order=np.lexsort((zp,si));first=order[np.r_[True,si[order][1:]!=si[order][:-1]]]   # Lowest layer of this paper there: all of it must clear
            need=S[si[first],2]-zp[first];hit=need>gap*.5+1e-7   # Less than half the gap left
            if not hit.any():continue
            bad=True;f=first[hit]
            w=np.clip(Wp[f],0.,1.);sw=(w*w).sum(-1);keep=sw>1e-12
            fv=V[f][keep];w=w[keep];k=(need[hit][keep]/sw[keep])[:,None]   # Barycentric: lifts each point by its need with the smallest vertex moves
            np.maximum.at(need_r,fv.ravel(),(push[fv]+k*w).ravel())
        if not bad:break
        raw=need_r;push=spread(raw)
    return push


# ---- Tape & objects stuck on the posters ------------------------------------------------------------
NODE_PIN='Poster Scatter · Attachments'
PIN_KEYS=('pin_place','pin_tape_share','pin_corners','pin_corner_chance','pin_corner_inset','pin_skip_lifted','pin_max_lift','pin_count','pin_chance','pin_follow','pin_follow_x','pin_follow_y','pin_follow_z','pin_spin','pin_scale','pin_scale_random','pin_poster_scale','pin_seed','pin_offset')


PIN_SOCKETS=[('Attach Points','INPUT','NodeSocketGeometry'),('Attach Collection','INPUT','NodeSocketCollection'),('Attach Object','INPUT','NodeSocketObject'),
             ('Use Object','INPUT','NodeSocketBool'),('Attachments','OUTPUT','NodeSocketGeometry')]


def make_pin_node():
    g=bpy.data.node_groups.get(NODE_PIN)
    if g and all(any(x.name==n for x in g.interface.items_tree) for n,_d,_k in PIN_SOCKETS):return g
    if g:g.nodes.clear();g.interface.clear()   # older version of the group: rebuild it in place (modifiers keep pointing at it)
    else:g=bpy.data.node_groups.new(NODE_PIN,'GeometryNodeTree')
    g.use_fake_user=True
    for name,direction,kind in PIN_SOCKETS:
        g.interface.new_socket(name=name,in_out=direction,socket_type=kind)
    def node(kind,name,x,y):
        n=g.nodes.new(kind);n.label=name;n.location=(x,y);return n
    a=node('NodeGroupInput','Points on the posters',-620,200)
    c=node('GeometryNodeCollectionInfo','Your tapes / objects',-620,-80)
    c.inputs['Separate Children'].default_value=True;c.inputs['Reset Children'].default_value=True
    idx=node('GeometryNodeInputNamedAttribute','Which object',-380,-260);idx.data_type='INT';idx.inputs['Name'].default_value='pin_index'
    rot=node('GeometryNodeInputNamedAttribute','Rotation',-380,-430);rot.data_type='FLOAT_VECTOR';rot.inputs['Name'].default_value='pin_rotation'
    sca=node('GeometryNodeInputNamedAttribute','Scale',-380,-610);sca.data_type='FLOAT';sca.inputs['Name'].default_value='pin_scale'
    ob=node('GeometryNodeObjectInfo','Your single object',-620,-330);ob.transform_space='ORIGINAL';ob.inputs['As Instance'].default_value=True
    sw=node('GeometryNodeSwitch','Collection or object',-300,-80);sw.input_type='GEOMETRY'
    inst=node('GeometryNodeInstanceOnPoints','Attachments',0,180);inst.inputs['Pick Instance'].default_value=True
    out=node('NodeGroupOutput','Result',280,180)
    for s_,o_,d_,i_ in [(a,'Attach Points',inst,'Points'),(a,'Attach Collection',c,'Collection'),(a,'Attach Object',ob,'Object'),(a,'Use Object',sw,'Switch'),
                        (c,'Instances',sw,'False'),(ob,'Geometry',sw,'True'),(sw,'Output',inst,'Instance'),(idx,'Attribute',inst,'Instance Index'),
                        (rot,'Attribute',inst,'Rotation'),(sca,'Attribute',inst,'Scale'),(inst,'Instances',out,'Attachments')]:g.links.new(s_.outputs[o_],d_.inputs[i_])
    return g


def pin_output(area,create=True):
    """Points object (child of the area) that instances the chosen tapes / objects."""
    s=area.poster_scatter;o=s.pin_output
    if o is not None and o.name in bpy.data.objects:return o
    if not create:return None
    me=bpy.data.meshes.new('Poster Attach Points');o=bpy.data.objects.new('Poster Attachments · '+area.name,me)
    for col in (s.output.users_collection if s.output else area.users_collection):col.objects.link(o)
    o.parent=area;o['ps_owned']=True;s.pin_output=o
    o.hide_viewport=not getattr(bpy.context.scene,'ps_show_results',True)
    mod=o.modifiers.new('Poster Attachments','NODES');mod.node_group=make_pin_node()
    return o


def set_pin_source(o,collection,obj):
    mod=o.modifiers.get('Poster Attachments')
    if not mod:return
    if mod.node_group is None or mod.node_group.name!=NODE_PIN or 'Use Object' not in [x.name for x in mod.node_group.interface.items_tree]:mod.node_group=make_pin_node()
    for name,value in (('Attach Collection',collection),('Attach Object',obj),('Use Object',obj is not None)):
        sock=next((x for x in mod.node_group.interface.items_tree if x.name==name),None)
        if sock is None:continue
        if hasattr(mod,'properties'):getattr(mod.properties.inputs,sock.identifier).value=value
        else:mod[sock.identifier]=value


def pin_source(s):
    """(collection, object, how many to pick from) for the chosen source."""
    if s.pin_source=='OBJECT':
        ob=s.pin_object
        return (None,ob,1) if ob is not None and ob.name in bpy.data.objects else (None,None,0)
    col=s.pin_collection
    return (col,None,len(col.objects)) if col else (None,None,0)


def pin_kind(o):
    """Kind of a tape / object: its pin_kind property, else the name before the first _ (TAPE_2 -> TAPE)."""
    k=o.get('pin_kind') if hasattr(o,'get') else None
    return str(k).upper() if k else o.name.split('_')[0].split('.')[0].upper()


def natural_spots(s,rng,w,h,local,kinds):
    """One way of holding per poster, count by size. Returns [(px,py,turn,index,spin)]."""
    area=w*h;size=0 if area<.035 else 2 if area>.12 else 1   # under ~A5 / over ~A3
    tapes=[k for k in kinds if 'TAPE' in k];others=[k for k in kinds if k not in tapes]
    share=s.pin_tape_share*(.6 if size==2 else 1.)
    use_tape=bool(tapes) and (not others or rng.random()<share)
    kind=rng.choice(tapes if use_tape else others);pool=kinds[kind]
    if use_tape:n=rng.choices((1,2,4),weights=((.55,.45,0),(.1,.65,.25),(0,.35,.65))[size])[0]
    else:n=rng.choices((1,2,4),weights=((.45,.55,0),(.1,.6,.3),(0,.3,.7))[size])[0]
    TL,TR,BR,BL=(-1,1,math.pi/4),(1,1,-math.pi/4),(1,-1,math.pi/4),(-1,-1,-math.pi/4)
    out=[]
    if use_tape:
        ins=min(s.pin_corner_inset,min(w,h)*.25)
        if n==1:   # one strip across the top edge, a little off centre
            u=rng.uniform(-.18,.18)*w;out.append((*local(u,h*.5-ins),0.,rng.choice(pool),rng.uniform(-1,1)*s.pin_spin))
        else:
            for sx,sy,turn in ((TL,TR) if n==2 else (TL,TR,BR,BL)):
                out.append((*local(sx*(w*.5-ins),sy*(h*.5-ins)),turn,rng.choice(pool),rng.uniform(-1,1)*s.pin_spin))
    else:
        m=max(.008,min(w,h)*.045)   # pins sit a little in from the corners
        one=rng.choice(pool)   # the same pin model all over one poster (one box of pins)
        cs=[(0,1)] if n==1 else [(-1,1),(1,1)] if n==2 else [(-1,1),(1,1),(1,-1),(-1,-1)]
        for sx,sy in cs:
            u=sx*(w*.5-m) if sx else rng.uniform(-.1,.1)*w
            out.append((*local(u,sy*(h*.5-m)),0.,one,rng.uniform(0,2*math.pi)))
    return out


def place_pins(area,records,catalog,positions,tilts,yaws,surfaces,base_count,curved,mesh):
    """Stick the user's tapes / objects onto the posters: at the pivot, along the top, at the corners or at random spots.
    They sit on top of whatever paper is there and turn with the poster (or stay upright).
    A spot where the paper is lifted off what is under it (curled corner, bent bottom) gets nothing: tape would not hold there."""
    s=area.poster_scatter;col,src_obj,n_obj=pin_source(s)
    o=pin_output(area,create=bool(s.pin_on and n_obj))
    if o is None:return 0
    me=o.data;me.clear_geometry()
    if not s.pin_on or not n_obj or not records:me.update();return 0
    ents=[];BB=np.zeros((len(surfaces),4))
    for k,e in enumerate(surfaces):
        P=np.array(e[3],np.float64).copy();P[:,2]+=e[2];ents.append((P,e[4]));BB[k]=e[5]
    def z_of(k,px,py):
        P,F=ents[k];z=layer_z(P,F,np.array([[px,py]]),True)[0]
        return float(z) if np.isfinite(z) else None
    def heights(px,py,upto):
        """Highest paper surface at (px,py) among surfaces [0, upto)."""
        best=None
        for k in np.flatnonzero((BB[:upto,0]<=px)&(px<=BB[:upto,2])&(BB[:upto,1]<=py)&(py<=BB[:upto,3])):
            z=z_of(int(k),px,py)
            if z is not None and (best is None or z>best):best=z
        return best
    n_all=len(ents)
    def top_z(px,py):return heights(px,py,n_all)
    def lifted(j,px,py):
        """How far paper j is off whatever lies under it at this spot (None = not on paper j)."""
        kj=base_count+j
        if kj>=n_all:return None
        zj=z_of(kj,px,py)
        if zj is None:return None
        zb=heights(px,py,kj)
        return zj-(zb if zb is not None else 0.)
    smap=SurfaceMap(mesh) if curved else None
    kinds={}
    if s.pin_place=='NATURAL':   # index = order of the objects in the collection (same order Collection Info instances them)
        for i,ob in enumerate(sorted(col.objects,key=lambda o:o.name) if col else []):kinds.setdefault(pin_kind(ob),[]).append(i)
    tape_idx={i for k,v in kinds.items() if 'TAPE' in k for i in v}
    upper=[]   # papers of scatters stacked on this one (sticky notes...): a pin there would poke through them
    if s.pin_place=='NATURAL':
        for b in [o for o in bpy.context.scene.objects if o!=area and getattr(o,'poster_scatter',None) and o.poster_scatter.enabled and area in stack_chain(o)]:
            for e in area_papers(b,area):
                xs=[q.x for q in e[3]];ys=[q.y for q in e[3]];upper.append((min(xs),min(ys),max(xs),max(ys)))
    CORNERS=(('TL',-1,1,math.pi/4),('TR',1,1,-math.pi/4),('BR',1,-1,math.pi/4),('BL',-1,-1,-math.pi/4))
    pts=[];idx=[];rots=[];scs=[];skipped=0;covered=0
    for j,(x,y,i_,angle,k) in enumerate(records):
        rng=random.Random(int.from_bytes(hashlib.blake2b(('pin|%d|%d|%.5f|%.5f'%(s.pin_seed,j,x,y)).encode(),digest_size=8).digest(),'big'))   # same picks every update
        if rng.random()>s.pin_chance:continue
        obj=catalog[i_];sc=s.scale*k;w=obj['width']*sc;h=obj['height']*sc;ca,sa=math.cos(angle),math.sin(angle)
        def local(u,v):return (x+ca*u-sa*v,y+sa*u+ca*v)
        spots=[]   # (px, py, extra turn[, object index, spin])
        if s.pin_place=='NATURAL':spots=natural_spots(s,rng,w,h,local,kinds) if kinds and w*h>=.012 else []   # sticky-note size papers hold themselves
        elif s.pin_place=='PIVOT':spots=[(positions[j][0],positions[j][1],0.)]
        elif s.pin_place=='CORNER':
            pick=[c for c in CORNERS if s.pin_corners=='ALL' or (s.pin_corners=='TOP' and c[2]>0)]
            if s.pin_corners=='RANDOM':
                pick=[c for c in CORNERS if rng.random()<s.pin_corner_chance]
                if not pick:pick=[CORNERS[rng.randrange(2)]]
            ins=min(s.pin_corner_inset,min(w,h)*.25)
            for _,sx,sy,turn in pick:
                spots.append((*local(sx*(w*.5-ins),sy*(h*.5-ins)),turn))
        else:
            for _ in range(max(1,s.pin_count)):
                u=rng.uniform(-.36,.36)*w;v=(rng.uniform(-.36,.36)*h) if s.pin_place=='RANDOM' else h*.5-min(w,h)*.06
                spots.append((*local(u,v),0.))
        for sp in spots:
            px,py,turn=sp[:3];pick=sp[3] if len(sp)>3 else None
            if pick is not None and pick not in tape_idx and any(b0-.007<=px<=b2+.007 and b1-.007<=py<=b3+.007 for b0,b1,b2,b3 in upper):covered+=1;continue
            z=top_z(px,py)
            if z is None:   # just past a curled / shifted edge: slide toward the middle of the paper until it is on it
                dx,dy=x-px,y-py;L_=math.hypot(dx,dy)
                for t_ in range(1,25):
                    if L_<1e-9:break
                    q=min(1.,t_*.0015/L_);z=top_z(px+dx*q,py+dy*q)
                    if z is not None:px,py=px+dx*q,py+dy*q;break
            if z is None:continue   # off the paper
            kj=base_count+j;zj=z_of(kj,px,py) if kj<n_all else None
            if zj is not None and z-zj>max(s.overlap_depth*2.,.0006):covered+=1;continue   # a later paper lies over this spot: the tape is under it
            if s.pin_skip_lifted and not s.rail_object:   # on a string the clip holds the photo: lifting doesn't matter there
                lf=lifted(j,px,py)
                if lf is not None and lf>s.pin_max_lift:skipped+=1;continue   # curled / bent up here: nothing to stick to
            spin=sp[4] if len(sp)>4 else rng.uniform(-1,1)*s.pin_spin
            if s.pin_follow:   # follow only the axes that are switched on (X = tilt, Y = side lean, Z = turn)
                rot=Matrix.Rotation((angle if s.pin_follow_z else 0.)+turn+spin,3,'Z')@Matrix.Rotation(yaws[j] if s.pin_follow_y else 0.,3,'Y')@Matrix.Rotation(tilts[j] if s.pin_follow_x else 0.,3,'X')
            else:rot=Matrix.Rotation(turn+spin,3,'Z')
            z+=s.pin_offset
            if smap is not None and s.layout=='RAIL':   # rail: same flat frame as the paper, taken at its clip point
                fx,fy=positions[j][0],positions[j][1];p0,right,up,n0=smap.frame(fx,fy,max(min(w,h)*.05,1e-4))
                pos=p0+right*(px-fx)+up*(py-fy)+n0*z;rot=Matrix((right,up,n0)).transposed()@rot
            elif smap is not None:   # curved wall: onto the real surface, turned with its tangent frame
                p0,right,up,n0=smap.frame(px,py,max(min(w,h)*.05,1e-4))
                pos=p0+n0*z;rot=Matrix((right,up,n0)).transposed()@rot
            else:pos=Vector((px,py,z))
            pts.append(tuple(pos));idx.append(pick if pick is not None else rng.randrange(n_obj));rots.append(tuple(rot.to_euler('XYZ')))
            scs.append(max(.01,s.pin_scale*(1+rng.uniform(-1,1)*s.pin_scale_random)*(sc if s.pin_poster_scale else 1.)))
    me.from_pydata(pts,[],[])
    for name,typ,vals in (('pin_index','INT',idx),('pin_rotation','FLOAT_VECTOR',rots),('pin_scale','FLOAT',scs)):
        a=me.attributes.new(name,typ,'POINT')
        if typ=='INT':a.data.foreach_set('value',vals)
        elif typ=='FLOAT_VECTOR':a.data.foreach_set('vector',[c for r in vals for c in r])
        else:a.data.foreach_set('value',vals)
    me.update();set_pin_source(o,col,src_obj);o.update_tag()
    o['ps_pins_skipped']=skipped;o['ps_pins_covered']=covered
    return len(pts)

def rebuild(area):
    s=area.poster_scatter
    if not s.cache or not s.output:return
    migrate_lift_units(s);migrate_rotation(s);ROT_MAP[area.as_pointer()]=rot_axis_map(area);TOPO.clear();faces_of={};tri_of={}
    if s.cached_topology!=topology_signature(s) or any(o.data.attributes.get('ps_rest_position') is None for o in s.cache.objects):refresh_sources(area)
    start=time.monotonic();mesh=area.data;mesh.calc_loop_triangles()
    verts=flat_points(mesh);tris=[tuple(t.vertices) for t in mesh.loop_triangles];curved=area_flat(mesh) is not None
    if not tris:raise ValueError('No faces to scatter on.')
    bvh=BVHTree.FromPolygons(verts,tris,all_triangles=True)
    mask=colors(mesh,MASK);groups=np.ones_like(mask);seeds=colors(mesh,SEED)
    def sample(x,y):
        pos,n,idx,dist=bvh.ray_cast(Vector((x,y,1)),Vector((0,0,-1)),2)
        if idx is None:return None
        ids=tris[idx];a,b,c=[verts[i] for i in ids]
        v0=b-a;v1=c-a;v2=pos-a
        den=v0.x*v1.y-v1.x*v0.y
        if abs(den)<1e-12:return None
        u=(v2.x*v1.y-v1.x*v2.y)/den;v=(v0.x*v2.y-v2.x*v0.y)/den
        weights=np.array([1-u-v,u,v]);return weights@mask[list(ids)],weights@groups[list(ids)],weights@seeds[list(ids)]
    bx0=min(v.x for v in verts);bx1=max(v.x for v in verts);by0=min(v.y for v in verts);by1=max(v.y for v in verts)
    gkey=(area.as_pointer(),len(verts),len(tris),round(s.check_step,5),hashlib.blake2b(mask[:,0].tobytes()+np.array([(v.x,v.y) for v in verts[:64]]).tobytes(),digest_size=12).digest())
    sample.grid=mask_grid(gkey,verts,tris,mask,(bx0,bx1,by0,by1),s.check_step/3)
    sample.mesh=(np.array([(v.x,v.y) for v in verts],np.float64),np.asarray(tris,np.int64).reshape(-1,3),mask,seeds)
    catalog=sorted(s.cache.objects,key=lambda o:o.name)
    pools=[[i for i,o in enumerate(catalog) if o['group']==g] for g in range(3)]
    lookup={o['source']:i for i,o in enumerate(catalog)}
    pinned_idx=[n for n,p in enumerate(s.manual) if p.poster and p.poster.name in lookup]
    pinned=[s.manual[n] for n in pinned_idx]
    frozen=None   # Click-to-grab keeps every other poster where it is (until a layout setting changes)
    if s.get('ps_frozen_key'):
        if s['ps_frozen_key']==placement_key(area,catalog,()).hex():
            F=list(s.get('ps_frozen',[]))
            frozen=[(F[i],F[i+1],int(F[i+2]),F[i+3],F[i+4]) for i in range(0,len(F)-4,5) if 0<=int(F[i+2])<len(catalog)]
        else:
            for key in ('ps_frozen_key','ps_frozen'):
                if key in s:del s[key]
    fixed=[(p.x,p.y,lookup[p.poster.name],p.angle,max(p.scale,.01)) for p in pinned]
    all_ids=list(range(len(catalog)));counts=source_usage(catalog,fixed);caps=repeat_caps(s,catalog);records=[]
    margin=0 if s.allow_overlap else s.gap
    stretch_fixed=[(max(p.sx,.01),max(p.sy,.01)) for p in pinned]
    rects=[rectangle(x,y,catalog[i]['width']*s.scale*k*ax+margin,catalog[i]['height']*s.scale*k*ay+margin,angle) for (x,y,i,angle,k),(ax,ay) in zip(fixed,stretch_fixed)]
    under=lower_footprints(area,margin)   # Fill Empty Space: papers of the layers below take up room like placed ones
    rects+=under
    x0=min(v.x for v in verts);x1=max(v.x for v in verts);y0=min(v.y for v in verts);y1=max(v.y for v in verts)
    candidate_rng=random.Random(s.seed)
    # Placement does not depend on press/lift/tilt -> reuse the last result if placement-affecting values are unchanged
    pkey=placement_key(area,catalog,[f+st for f,st in zip(fixed,stretch_fixed)]) if frozen is None else None   # stretch changes the free space too
    if pkey is not None and under:pkey+=hashlib.blake2b(np.round(np.array([[c for p in r for c in p] for r in under],np.float64),4).tobytes(),digest_size=8).digest()
    hit=PLACE_CACHE.get(area.as_pointer())
    if frozen is not None:pass
    elif hit and hit[0]==pkey:records=list(hit[1])
    else:
        if s.layout=='PACK':records=packed_records(s,catalog,sample,(x0,x1,y0,y1),fixed,under)
        if s.layout=='RAIL' and s.count:
            records=rail_records(s,catalog,sample,rail_polylines(area),caps,counts)
        if s.layout=='GRID' and s.count:
            records=grid_records(s,catalog,sample,(x0,x1,y0,y1),fixed,caps,counts)
        if s.layout=='RANDOM' and s.count:
            records=random_records(s,catalog,sample,(x0,x1,y0,y1),fixed,caps,counts,rects,margin)
        if under and s.layout!='RANDOM':   # Grid / Pack / Rail: drop the papers that would cover the layers below
            idx_=BoxIndex(under);keep=[]
            for r in records:
                o=catalog[r[2]];box=rectangle(r[0],r[1],o['width']*s.scale+margin,o['height']*s.scale+margin,r[3])
                if placement_clear(box,idx_,s):keep.append(r)
            records=keep
        PLACE_CACHE[area.as_pointer()]=(pkey,list(records))
    def scaled(j,r):   # Random scale around the source pivot: the pivot stays put, the paper grows or shrinks from it
        if s.scale_random<=0:return (*r[:4],1.)
        x,y,idx,a=r[:4];key=('scale|%.7f|%.7f|%d|%d'%(x,y,j,s.seed)).encode()
        k=1.+(int.from_bytes(hashlib.blake2b(key,digest_size=8).digest(),'big')/(2**64-1)*2-1)*s.scale_random
        o=catalog[idx];cx=o['center_x']*s.scale;cy=o['center_y']*s.scale;c,sn=math.cos(a),math.sin(a)
        return (x+(c*cx-sn*cy)*(k-1.),y+(sn*cx+c*cy)*(k-1.),idx,a,k)
    if frozen is not None:records=frozen+fixed;man_off=len(frozen)   # Grabbed posters sit on top of the kept ones
    else:records=fixed+[scaled(j,r) for j,r in enumerate(records)];man_off=0
    kinds=[('M',pinned_idx[j-man_off]) if man_off<=j<man_off+len(fixed) else ('A',tuple(records[j])) for j in range(len(records))]
    picks=[]
    extra=[]
    for o in pressers(area):extra+=[e[0] for e in area_papers(o,area)]
    blocked,pressed=covered_curls(s,catalog,records,extra)
    for j,p in enumerate(pinned):   # Manually placed posters with 'No Lift' stay flat
        if p.no_lift:blocked[man_off+j]={k:0. for k in ('B','L','R','BL','BR')}
    bent=sync_bent_instances(area,catalog,records,blocked)
    stretch={man_off+n:st for n,st in enumerate(stretch_fixed) if abs(st[0]-1)>1e-6 or abs(st[1]-1)>1e-6}
    for j,(ax,ay) in stretch.items():   # Width / height stretch of a manual poster (around its pivot); re-bent from cache next time
        me_=bent[j].data;C=np.empty(len(me_.vertices)*3,np.float64);me_.vertices.foreach_get('co',C);C=C.reshape(-1,3)
        C[:,0]*=ax;C[:,1]*=ay;me_.vertices.foreach_set('co',C.ravel());me_.update();bent[j]['bend_key']=''
    positions=[];surfaces=base_surfaces(area);base_count=len(surfaces)
    rmap=ROT_MAP[area.as_pointer()];local_of={w:(i,sg) for w,(i,sg) in rmap.items()}
    def local_xy(j,x,y):   # Tilt (paper X) and turn (paper Y) from the world-axis X Y Z settings; each axis has its own random
        out=[0.,0.,0.]
        for w in range(3):
            i,sg=local_of[w]
            if i==2:continue   # The surface spin is already in the placement angle
            key=('rot%d|%.7f|%.7f|%d|%d'%(w,x,y,j,s.lift_seed)).encode()
            v=int.from_bytes(hashlib.blake2b(key,digest_size=8).digest(),'big')/(2**64-1)*2-1
            out[i]+=sg*rot_world(s,w,v)
        return out[0],out[1]
    rots=[local_xy(j,r[0],r[1]) for j,r in enumerate(records)]   # Not pressed: rotation is set on purpose, contact stacking keeps papers apart
    tilts=[rx for rx,ry in rots];yaws=[ry for rx,ry in rots]
    # Overlap check: bucket into cells so only nearby ones are compared
    sizes_=[max(catalog[r[2]]['width'],catalog[r[2]]['height'])*s.scale*r[4] for r in records] or [1.]
    bucket=max(sorted(sizes_)[len(sizes_)//2],1e-3);buckets={}
    def cells(bb):
        return [(i,j) for i in range(int(math.floor(bb[0]/bucket)),int(math.floor(bb[2]/bucket))+1)
                      for j in range(int(math.floor(bb[1]/bucket)),int(math.floor(bb[3]/bucket))+1)]
    def add_entry(e):
        if len(e)<6:e.append(aabb(e[0]))
        if not isinstance(e[3],np.ndarray):e[3]=np.array([tuple(p) for p in e[3]],np.float64).reshape(-1,3)
        e.append(len(add_entry.order));add_entry.order.append(e)
        for c in cells(e[5]):buckets.setdefault(c,[]).append(e)
    add_entry.order=[]
    for e in surfaces:add_entry(e)
    for j,(x,y,idx,angle,k) in enumerate(records):
        obj=catalog[idx];rotation=Matrix.Rotation(angle,3,'Z')@Matrix.Rotation(yaws[j],3,'Y')@Matrix.Rotation(tilts[j],3,'X');sc=s.scale*k
        ax_,ay_=stretch.get(j,(1.,1.))
        center=Matrix.Rotation(angle,3,'Z')@Matrix.Rotation(yaws[j],3,'Y')@Vector((obj['center_x']*sc*ax_,obj['center_y']*sc*ay_,0))
        me_=bent[j].data;nv=len(me_.vertices);V=np.empty(nv*3,np.float64);me_.vertices.foreach_get('co',V)
        V=(V.reshape(-1,3)*sc)@np.array(rotation,np.float64).T      # Transform vertices all at once
        # Rail: the clip point (pivot) stays on the line whatever the rotation; papers hang free, so no whole-paper lift
        depth=s.offset if s.layout=='RAIL' else s.offset-min(0.,float(V[:,2].min()))
        pts=V+np.array([x-center.x,y-center.y,0.])
        box=footprint(pts,x,y,angle)   # Overlap tests use where the paper really is, not its layout rectangle
        bb=aabb(box);seen=set();near=[]
        for c in cells(bb):
            for e in buckets.get(c,()):
                if e[6] not in seen:seen.add(e[6]);near.append(e)
        near.sort(key=lambda e:e[6])
        tkey=(bent[j].get('source_mesh'),nv,len(me_.polygons))   # Papers cut from one source share their mesh edges
        if tkey not in faces_of:
            E_=np.empty(len(me_.edges)*2,np.int64);me_.edges.foreach_get('vertices',E_);faces_of[tkey]=E_.reshape(-1,2)
        pedges=faces_of[tkey];faces=render_tris(me_,tri_of)   # Overlaps are checked on the triangles Blender really draws
        if s.grid_conform:   # Any overlapping layout: rest on the papers below instead of raising the whole paper
            for _ in range(3):
                push=conform_push(s,me_,pts,depth,box,bb,near,faces,pedges)
                if push is None or float(push.max())<=0.:break
                if s.layout=='RAIL':   # Keep the clip point on the line: the top may move only a hair, lower down the paper leans out over the one below
                    ux,uy=-math.sin(angle),math.cos(angle);H=max(obj['height']*sc,1e-6)
                    below=np.clip(-((pts[:,0]-(x-center.x))*ux+(pts[:,1]-(y-center.y))*uy)/H,0.,1.)
                    push=np.minimum(push,RAIL_PIVOT_SLACK+push*below)
                    if float(push.max())<=0.:break
                loc=(push[:,None]*np.array(rotation,np.float64)[2][None,:])/max(sc,1e-12)   # Wall-normal rise in the paper's local space
                C=np.empty(nv*3,np.float64);me_.vertices.foreach_get('co',C)
                me_.vertices.foreach_set('co',(C.reshape(-1,3)+loc).ravel());me_.update()
                bent[j]['bend_key']=''   # Shape now depends on the papers below: start again from its natural bend next update
                pts=pts.copy();pts[:,2]+=push
                again=render_tris(me_,tri_of)
                if again is faces:break
                faces=again   # Rising changed how a bent face splits into triangles: check once more with the new split
        else:
            for entry in near:   # Raise the whole paper above the real (bent) papers below where they overlap
                previous,_,pdepth,ppts,pfaces=entry[:5]
                if not aabb_hit(bb,entry[5]) or separated(box,previous):continue
                ax0=max(bb[0],entry[5][0]);ax1=min(bb[2],entry[5][2]);ay0=max(bb[1],entry[5][1]);ay1=min(bb[3],entry[5][3])
                best=rise_over(pts,faces,ppts,pfaces,(ax0,ax1,ay0,ay1))
                if best is not None:depth=max(depth,pdepth+best+s.overlap_depth)
            if s.layout=='RAIL':depth=min(depth,s.offset+RAIL_PIVOT_SLACK)   # the clip point stays on the line
        positions.append((x-center.x,y-center.y,depth));e=[box,None,depth,pts,faces];surfaces.append(e);add_entry(e)
        picks.append(([(p.x,p.y) for p in box],float(depth+float(pts[:,2].max()-pts[:,2].min()) if len(pts) else depth)))
    try:n_pins=place_pins(area,records,catalog,list(positions),tilts,yaws,surfaces,base_count,curved,mesh)   # tapes / objects on the posters
    except Exception as exc:n_pins=0;s['ps_note']='Attachments: '+str(exc)
    if curved:   # Move placement and overlap heights computed in the unfolded plane onto the real curved surface
        smap=SurfaceMap(mesh)
        for j,(x,y,idx,angle,k) in enumerate(records):
            ox,oy,depth=positions[j];me=bent[j].data
            rotation=Matrix.Rotation(angle,3,'Z')@Matrix.Rotation(yaws[j],3,'Y')@Matrix.Rotation(tilts[j],3,'X');sc=s.scale*k
            flat=[Vector((ox,oy,depth))+rotation@(v.co*sc) for v in me.vertices]
            if s.surface_mode=='CONFORM' and s.layout!='RAIL':
                out=[]
                for f in flat:
                    p,n=smap.map(f.x,f.y);out.append(p+n*f.z)
            else:
                obj=catalog[idx];e=max(min(obj['width'],obj['height'])*sc*.05,1e-4)
                fx,fy=(ox,oy) if s.layout=='RAIL' else (x,y)   # Rail: hang flat from the clip point, facing the way the line runs there
                p0,right,up,n0=smap.frame(fx,fy,e)
                out=[p0+right*(f.x-fx)+up*(f.y-fy)+n0*f.z for f in flat]
                push=0.
                for f,v3 in zip(flat,out):   # Push paper edges out so they don't pierce the surface in concave spots
                    p,n=smap.map(f.x,f.y);need=(f.z-(v3-p).dot(n))/max(n.dot(n0),.3)
                    if need>push:push=need
                if push>0 and s.layout!='RAIL':out=[v+n0*push for v in out]
            me.vertices.foreach_set('co',[c for v in out for c in v]);me.update()
        positions=[(0.,0.,0.)]*len(records)
    PICKS[area.as_pointer()]={'picks':picks,'kinds':kinds,'names':[o['source'] for o in catalog],'key':placement_key(area,catalog,()).hex()}
    result=s.output.data;result.clear_geometry();result.from_pydata(positions,[],[])
    for name,typ in [('poster_index','INT'),('poster_rotation','FLOAT_VECTOR'),('poster_scale','FLOAT')]:
        old=result.attributes.get(name)
        if old:result.attributes.remove(old)
        a=result.attributes.new(name,typ,'POINT')
        if typ=='INT':a.data.foreach_set('value',list(range(len(records))))
        elif typ=='FLOAT_VECTOR':a.data.foreach_set('vector',[0.]*3*len(records) if curved else [v for j,r in enumerate(records) for v in (tilts[j],yaws[j],r[3])])
        else:a.data.foreach_set('value',[1.]*len(records) if curved else [s.scale*r[4] for r in records])
    result.update();s.output.update_tag();s.build_id=(s.build_id+1)%1000000000
    if s.get('ps_skipped'):s['ps_note']='Excluded non-flat sources: '+s['ps_skipped']
    elif 'ps_note' in s:del s['ps_note']
    s.status='Auto %d · Manual %d%s%s · %.2fs'%(len(records)-len(fixed),len(fixed),' · Attached %d'%n_pins if n_pins else '',' · others kept' if frozen is not None else '',time.monotonic()-start)
    if s.repeat and s.repeat_limited and all(not quota_available(caps,source_usage(catalog,records),i) for i in all_ids):s.status+=' · repeat limit reached'
    ps_area_invisible(area)   # After placement, area faces are always hidden in renders (including viewport render)
    try:ps_apply_sources(bpy.context.scene)   # After placement, hide the source poster gallery unless 'Show Source Posters' is on
    except Exception:pass
    return records

def signature(area):
    s=area.poster_scatter;h=hashlib.blake2b(digest_size=12)
    for name in (MASK,SEED):h.update(colors(area.data,name).tobytes())
    h.update(str((s.stack_mode,[(b.name,b.poster_scatter.build_id) for b in stack_chain(area)])).encode())   # Re-place when any layer below changes
    for o in pressers(area):   # Re-press when papers in a stacked-on area move (height ignored to avoid infinite loops)
        me=o.poster_scatter.output.data if o.poster_scatter.output else None
        if me:h.update(np.round(np.array([v.co.xy for v in me.vertices],np.float32),4).tobytes())
    h.update(str((round(s.scale_random,6),s.press,s.press_strength,s.press_falloff,s.grid_conform,round(s.grid_stiffness,4),s.grid_overlap,s.grid_jitter,s.grid_fill,s.grid_stagger,s.surface_mode,s.layout,s.count,s.seed,s.gap,(s.rot_x_on,s.rot_y_on,s.rot_z_on,tuple(round(getattr(s,'rot_%s_%s'%(ax,k)),6) for ax in 'xyz' for k in ('angle','rand'))),s.scale,s.offset,s.repeat,s.tilt,s.tilt_random,s.tilt_min,s.bottom_lift_percent,s.allow_overlap,s.overlap_ratio,s.overlap_depth)).encode())
    ensure_repeat_ranges(s)
    h.update(str((s.repeat_limited,[(r.upper,r.limit) for r in s.repeat_ranges])).encode())
    h.update(str((s.lift_enabled,s.lift_random,s.lift_min_percent,s.lift_seed,round(s.curl_shape,4),topology_signature(s),s.curl_bottom,s.curl_mix,s.side_pair,s.corner_pair,
                  s.attach_mode,s.roll_enabled,s.roll_angle,s.roll_min,s.tape_position,s.tape_side,s.tape_curve)).encode())
    h.update(str([(p.poster.name if p.poster else '',p.x,p.y,p.angle,p.scale,p.sx,p.sy,p.no_lift) for p in s.manual]).encode())
    h.update(str((s.pin_on,s.pin_source,s.pin_collection.name if s.pin_collection else '',len(s.pin_collection.objects) if s.pin_collection else 0,
                  s.pin_object.name if s.pin_object else '',[getattr(s,k) for k in PIN_KEYS])).encode())
    if s.layout=='RAIL':h.update(rail_key(area))
    return h.digest()

def tick():
    global BUSY
    if BUSY:return .4
    BUSY=True
    try:
        make_node()
        for area in bpy.context.scene.objects:
            s=area.poster_scatter
            if not s.enabled or not s.live or not s.output or not s.cache or area.mode=='EDIT':continue
            try:
                key=area.as_pointer()
                if s.collection:   # posters deleted / added in the Outliner: re-read the sources so the wall follows
                    srcs=tuple(sorted(o.name for o in s.collection.all_objects if o.type=='MESH'))
                    old=SOURCE_SETS.get(key);SOURCE_SETS[key]=srcs
                    if old is not None and old!=srcs and srcs:
                        refresh_sources(area);rebuild(area);SIGNATURES[key]=signature(area);continue
                sig=signature(area)
                if SIGNATURES.get(key)!=sig:
                    # Recomputing a heavy area continuously while dragging a slider feels like a freeze,
                    # so if the last compute took over 0.5s, only compute once the value is unchanged for 0.8s.
                    now=time.monotonic();pend=PENDING.get(key)
                    if LAST_COST.get(key,0)>.5 and (pend is None or pend[0]!=sig or now-pend[1]<.8):
                        if pend is None or pend[0]!=sig:PENDING[key]=(sig,now)
                        continue
                    PENDING.pop(key,None);t0=time.monotonic()
                    rebuild(area);SIGNATURES[key]=sig;LAST_COST[key]=time.monotonic()-t0
            except Exception as exc:s.status='Placement error: '+str(exc);s.live=False
    finally:BUSY=False
    return .4

def current(context):
    o=context.object
    if o and o.poster_scatter.enabled:return o
    if o and o.parent and o.parent.poster_scatter.enabled:return o.parent
    if o:
        for c in o.children:   # A rail shows the posters hung from it
            if c.get('ps_rail_auto') and c.poster_scatter.enabled:return c

def range_upper_get(self):
    return self.get('upper',1.)


def range_upper_set(self,value):
    owner=self.id_data
    s=owner.poster_scatter_setup if isinstance(owner,bpy.types.Scene) else owner.poster_scatter
    rules=s.repeat_ranges
    idx=next((i for i,r in enumerate(rules) if r.as_pointer()==self.as_pointer()),-1)
    if idx<0:self['upper']=float(value);return
    lower=rules[idx-1].upper if idx else 0.
    upper=rules[idx+1].upper if idx+1<len(rules) else 1.
    self['upper']=max(lower+.0001,min(upper-(.0001 if idx+1<len(rules) else 0.),float(value)))


class PS_RepeatRange(bpy.types.PropertyGroup):
    upper:FloatProperty(name=_T('Area Range End'),min=0,max=1,precision=3,get=range_upper_get,set=range_upper_set,description=_T('Boundary with the next range. Smallest area is 0, largest is 1.'))
    limit:IntProperty(name=_T('Max Count'),default=2,min=0,max=2000,description=_T('Maximum copies per source in this range, including first and manual placements. 0 excludes it from auto placement.'))


def placement_changed(self,context):
    area=self.id_data
    if not isinstance(area,bpy.types.Object):return
    s=area.poster_scatter
    if _SUPPRESS[0]:return
    if not PLACERS:   # Editing a manual poster in the panel: the others follow the layout rules again
        for key in ('ps_frozen_key','ps_frozen'):
            if key in s:del s[key]
    if s.live or not s.output or not s.cache:return   # If live preview is on, the timer applies it
    try:rebuild(area);SIGNATURES[area.as_pointer()]=signature(area)
    except Exception as exc:s.status='Placement error: '+str(exc)


class PS_Placement(bpy.types.PropertyGroup):
    poster:PointerProperty(type=bpy.types.Object)
    x:FloatProperty(update=placement_changed);y:FloatProperty(update=placement_changed)
    angle:FloatProperty(name=_T('Angle'),subtype='ANGLE',update=placement_changed)
    no_lift:BoolProperty(name=_T('No Lift'),default=False,update=placement_changed,description=_T('Place only this poster flat, without lift or bend'))
    scale:FloatProperty(name=_T('Scale'),default=1,min=.05,max=20,soft_min=.1,soft_max=5,step=5,precision=2,update=placement_changed,
                        description=_T('Scale factor for this poster only (overall scale × this value)'))
    sx:FloatProperty(name=_T('Width'),default=1,min=.05,max=20,soft_min=.1,soft_max=5,step=5,precision=2,update=placement_changed,description=_T('Extra stretch across (S then X while placing)'))
    sy:FloatProperty(name=_T('Height'),default=1,min=.05,max=20,soft_min=.1,soft_max=5,step=5,precision=2,update=placement_changed,description=_T('Extra stretch up-down (S then Y or Z while placing)'))

REPEAT_DEFAULT=2
_COUNT_GUARD=[False]


def auto_count(s):
    n=s.source_count
    if not s.repeat:return n
    caps=[r.limit for r in s.repeat_ranges] if (s.repeat_limited and s.repeat_ranges) else [REPEAT_DEFAULT]
    return n*max(caps) if s.repeat_limited else n*REPEAT_DEFAULT


def apply_auto_count(s):
    if not s.count_auto:return
    _COUNT_GUARD[0]=True
    try:s.count=auto_count(s)
    finally:_COUNT_GUARD[0]=False


def count_changed(s,context):
    if not _COUNT_GUARD[0]:s.count_auto=False   # Turn off auto when the user changes it manually


def count_auto_changed(s,context):apply_auto_count(s)


def repeat_changed(s,context):
    if s.repeat:ensure_repeat_ranges(s)
    apply_auto_count(s)


def minimum_lift_changed(s,context):
    if s.lift_min_percent>s.bottom_lift_percent:s.bottom_lift_percent=s.lift_min_percent


def maximum_lift_changed(s,context):
    if s.lift_min_percent>s.bottom_lift_percent:s.lift_min_percent=s.bottom_lift_percent


class PS_Settings(bpy.types.PropertyGroup):
    enabled:BoolProperty(default=False)
    curved:BoolProperty(default=False,options={'HIDDEN'})
    source_surface:PointerProperty(name=_T('Source Face Object'),type=bpy.types.Object,description=_T('Object that held the faces picked when the area was created'),update=lambda s,c:source_hide_changed(s,c))
    hide_source:BoolProperty(name=_T('Hide Source Face in Render'),default=False,update=lambda s,c:source_hide_changed(s,c),
        description=_T('Hides the plane picked when creating the area from renders. The scatter area keeps its own copy of the shape, so placement is not affected. Turn this off if you created it from the wall itself.'))
    build_id:IntProperty(default=0,options={'HIDDEN'})
    stack_on:PointerProperty(name=_T('Stack on Lower Scatter'),type=bpy.types.Object,
        poll=lambda self,o:stack_poll(self,o),update=lambda s,c:stack_on_changed(s,c),
        description=_T('Pick another scatter area on the same wall. Its posters (and every layer under it) are taken into account: fill the empty space around them, or lie on top of them'))
    stack_mode:EnumProperty(name=_T('With Posters Below'),items=_T_items([
        ('FILL','Fill Empty Space','Place posters only where the layers below have none, so nothing covers them'),
        ('TOP','Stack on Top','Lay posters over the layers below (including lifted shapes) without intersecting them')]),
        default='TOP',update=lambda s,c:stack_mode_changed(s,c))
    surface_mode:EnumProperty(name=_T('Curved Surface Mode'),items=_T_items([
        ('CONFORM','Conform to Curve','Paper bends along the surface and sticks completely (e.g. flyers on a pole)'),
        ('FLAT','Keep Flat','Paper stays flat and touches the curved surface. It is lifted over concave spots so it never intersects')]),default='CONFORM')
    conform_faces:IntProperty(name=_T('Curve Fit · Across'),default=10,min=1,max=40,description=_T('Columns across each paper so it can follow a sideways curve (rails, round walls). 1 = no extra cuts. Raise for tight curves'))
    conform_faces_v:IntProperty(name=_T('Curve Fit · Down'),default=10,min=1,max=40,description=_T('Rows down each paper so it can follow an up-down curve (domes, arches). 1 = no extra cuts'))
    layout:EnumProperty(name=_T('Layout'),items=_T_items([('RANDOM','Random','Scatter naturally at random positions.'),('PACK','Fill Gaps','Spread large posters over the whole area and fit small posters into the remaining gaps. Keeps source sizes.'),
        ('GRID','Overlap Grid',''),
        ('RAIL','Along Rail','Hang papers along a curve or mesh edges, like order tickets on a rail or notes on a string')]),default='RANDOM')
    grid_overlap:FloatProperty(name=_T('Overlap'),default=.2,min=-.3,max=.6,subtype='FACTOR',description=_T('How much neighbors overlap. 0 means touching, higher overlaps more. Negative leaves gaps.'))
    grid_jitter:FloatProperty(name=_T('Jitter'),default=.25,min=0,max=.6,subtype='FACTOR',description=_T('How far papers drift from the grid. Higher looks more natural.'))
    grid_fill:FloatProperty(name=_T('Fill'),default=1,min=.1,max=1,subtype='FACTOR',description=_T('Chance to place a paper in each cell. Lower leaves random empty spots.'))
    grid_stagger:BoolProperty(name=_T('Brick Offset'),default=True,description=_T('Shift every other row by half a cell to hide the grid look'))
    grid_conform:BoolProperty(name=_T('Rest on Papers Below'),default=True,description=_T('A paper rises only where it actually lies over a paper below and ramps over its edge, instead of the whole paper being raised. Stacks no longer float. Off: the older whole-paper raise'))
    grid_stiffness:FloatProperty(name=_T('Paper Stiffness'),default=.35,min=0,max=1,subtype='FACTOR',description=_T('How far the rise spreads from an overlap into the rest of the paper. 0 bends right at the lower edge, higher ramps more gently'))
    rail_object:PointerProperty(name=_T('Rail'),type=bpy.types.Object,poll=lambda self,o:o.type in {'CURVE','MESH'} and o!=self.id_data and not o.get('ps_owned') and not o.poster_scatter.enabled,
        description=_T('A curve, or a mesh whose edges (selected ones, if marked) form the rail. Papers hang from it'))
    rail_hang:EnumProperty(name=_T('Hang'),items=_T_items([('GRAVITY','Straight Down','Papers hang straight down whatever the rail angle'),('RAIL','Square to Rail','Papers hang square to the rail, following its slope and curves')]),default='GRAVITY')
    rail_overlap:FloatProperty(name=_T('Overlap'),default=.15,min=-3,max=.9,subtype='FACTOR',description=_T('How much each paper covers the next, as a share of its width. Negative leaves gaps: -1 = a gap one paper wide, -3 = three papers wide'))
    rail_jitter:FloatProperty(name=_T('Spacing Jitter'),default=.3,min=0,max=1,subtype='FACTOR',description=_T('Random variation of the spacing'))
    rail_drop:FloatProperty(name=_T('Drop'),default=0,min=-1,max=1,soft_min=-.05,soft_max=.05,subtype='DISTANCE',description=_T('How far below the rail the top edge sits. Negative tucks the top above the line (behind a clip or lip)'))
    rail_drop_random:FloatProperty(name=_T('Drop Random'),default=.003,min=0,max=1,soft_max=.05,subtype='DISTANCE',description=_T('Random up/down variation of each paper'))
    rail_swing:FloatProperty(name=_T('Swing'),default=math.radians(2),min=0,max=math.radians(45),subtype='ANGLE',description=_T('Random rotation around the clip point'))
    rail_order:EnumProperty(name=_T('Stacking'),items=_T_items([('FORWARD','Newer on Top','Each paper overlaps the one before it'),('BACKWARD','Older on Top','Each paper tucks under the one before it'),('RANDOM','Random','Random stacking order')]),default='FORWARD')
    rail_pick:EnumProperty(name=_T('Photo Order'),items=_T_items([('SHUFFLE','Shuffle','Photos are mixed along the rail · change Random Seed for another mix'),('NUMBER','By Number','Photos hang in their atlas number order (1, 2, 3...) · renumber them in the Atlas layout with W')]),default='SHUFFLE')
    rail_slide:FloatProperty(name=_T('Slide'),default=0,soft_min=-2,soft_max=2,subtype='DISTANCE',description=_T('Moves all papers along the rail. Keyframe it to make them travel'))
    rail_wrap:BoolProperty(name=_T('Wrap Around'),default=False,description=_T('Papers sliding past the end come back at the start (closed rails always wrap)'))
    rail_reverse:BoolProperty(name=_T('Reverse Direction'),default=False,description=_T('Start from the other end of the rail'))
    rail_margin:FloatProperty(name=_T('End Margin'),default=.05,min=0,max=5,soft_max=.5,subtype='DISTANCE',
        description=_T('Keeps papers this far from both ends of an open rail (away from the nails / hooks it hangs from)'))
    collection:PointerProperty(name=_T('Poster Collection'),type=bpy.types.Collection,description=_T('The collection holding your posters: flat planes in their local XY, +Y up (Poster Atlas makes these)'))
    cache:PointerProperty(type=bpy.types.Collection)
    render_cache:PointerProperty(type=bpy.types.Collection)
    output:PointerProperty(type=bpy.types.Object)
    count:IntProperty(name=_T('Count'),default=0,min=0,max=2000,description=_T('How many posters to place at most. Fewer are placed if space runs out. Typing a number unlinks it from the poster count'),update=count_changed)
    count_auto:BoolProperty(name=_T('Link Count to Posters'),default=True,description=_T('When on, the max count matches the number of posters provided (× repeats when repeat is on).'),update=count_auto_changed)
    source_count:IntProperty(default=0)
    seed:IntProperty(name=_T('Random Seed'),default=0,min=0,max=1000000,description=_T('Change it to get a different arrangement with the same settings'))
    scale:FloatProperty(name=_T('Scale'),default=1,min=.01,max=100,description=_T('Size of every placed poster compared with its source'))
    gap:FloatProperty(name=_T('Minimum Gap'),default=.01,min=0,max=1,subtype='DISTANCE',description=_T('Smallest space kept between posters when they may not overlap'))
    rotation:FloatProperty(name=_T('Rotation Range (old)'),default=0,min=0,max=math.pi,subtype='ANGLE',description=_T('Older setting, moved into the X Y Z rotation automatically'))
    rot_schema:IntProperty(default=0,options={'HIDDEN'})
    rot_angle:FloatProperty(name=_T('Angle'),default=0,min=-math.pi,max=math.pi,soft_min=-math.pi/2,soft_max=math.pi/2,subtype='ANGLE',description=_T('Fixed rotation around every axis that is on'))
    rot_rand:FloatProperty(name=_T('Random'),default=0,min=0,max=math.pi,soft_max=math.pi/4,subtype='ANGLE',description=_T('Each paper adds a random amount between minus and plus this, drawn separately for every axis that is on'))
    scale_random:FloatProperty(name=_T('Random Scale'),default=0,min=0,max=.9,subtype='FACTOR',description=_T('Each paper is scaled randomly between 1 minus and 1 plus this, around its source pivot. 0.2 gives 0.8 to 1.2 times'))
    rot_x_on:BoolProperty(name=_T('X'),default=False,description=_T('Rotate papers around the world X axis. On a wall: tilts papers forward or back'))
    rot_y_on:BoolProperty(name=_T('Y'),default=False,description=_T('Rotate papers around the world Y axis. On a wall: spins papers flat on the wall'))
    rot_z_on:BoolProperty(name=_T('Z'),default=False,description=_T('Rotate papers around the world Z axis. On a wall: turns papers around the vertical axis'))
    rot_x_angle:FloatProperty(name=_T('X Angle'),default=0,min=-math.pi,max=math.pi,soft_min=-math.pi/2,soft_max=math.pi/2,subtype='ANGLE',description=_T('Fixed rotation around X'))
    rot_y_angle:FloatProperty(name=_T('Y Angle'),default=0,min=-math.pi,max=math.pi,soft_min=-math.pi/2,soft_max=math.pi/2,subtype='ANGLE',description=_T('Fixed rotation around Y'))
    rot_z_angle:FloatProperty(name=_T('Z Angle'),default=0,min=-math.pi,max=math.pi,soft_min=-math.pi/2,soft_max=math.pi/2,subtype='ANGLE',description=_T('Fixed rotation around Z'))
    rot_x:FloatProperty(name=_T('Angle'),default=0,min=-math.pi,max=math.pi,soft_min=-math.pi/2,soft_max=math.pi/2,subtype='ANGLE',description=_T('Fixed rotation around world X'))
    rot_y:FloatProperty(name=_T('Angle'),default=0,min=-math.pi,max=math.pi,soft_min=-math.pi/2,soft_max=math.pi/2,subtype='ANGLE',description=_T('Fixed rotation around world Y'))
    rot_z:FloatProperty(name=_T('Angle'),default=0,min=-math.pi,max=math.pi,soft_min=-math.pi/2,soft_max=math.pi/2,subtype='ANGLE',description=_T('Fixed rotation around world Z'))
    rot_x_rand:FloatProperty(name=_T('Random'),default=0,min=0,max=math.pi,soft_max=math.pi/4,subtype='ANGLE',description=_T('Each paper adds a random amount between minus and plus this around world X'))
    rot_y_rand:FloatProperty(name=_T('Random'),default=0,min=0,max=math.pi,soft_max=math.pi/4,subtype='ANGLE',description=_T('Each paper adds a random amount between minus and plus this around world Y'))
    rot_z_rand:FloatProperty(name=_T('Random'),default=0,min=0,max=math.pi,soft_max=math.pi/4,subtype='ANGLE',description=_T('Each paper adds a random amount between minus and plus this around world Z'))
    yaw:FloatProperty(name=_T('Turn (Z)'),default=0,min=0,max=math.radians(45),subtype='ANGLE',description=_T('Random turn of each paper around its own up axis (world Z on a wall), so one side comes off the surface. The low side stays on the surface'))
    offset:FloatProperty(name=_T('Surface Offset'),default=.001,min=.0001,max=.1,subtype='DISTANCE',description=_T('Distance between the surface and the lowest paper, so they never flicker into each other'))
    tilt_random:BoolProperty(name=_T('Vary per Poster'),default=False,description=_T('Random tilt between min and max for each poster (reshuffle with the lift seed)'))
    tilt_min:FloatProperty(name=_T('Minimum Tilt'),default=0,min=0,max=math.radians(60),subtype='ANGLE')
    tilt:FloatProperty(name=_T('Tilt from Pivot'),description=_T('Tilts the bottom away from the wall around the source pivot.'),default=0,min=0,max=math.radians(60),subtype='ANGLE')
    lift_enabled:BoolProperty(name=_T('Enable Paper Lift · Bend'),default=False,description=_T('When off, papers return to flat. Pivot tilt is separate.'))
    bottom_lift_percent:FloatProperty(name=_T('Lift Ratio'),description=_T('Lift as a ratio of the poster height. At 5%, a 100 mm tall paper lifts up to 5 mm. Limited so it never exceeds the bending length. Negative values bend backward: on floors the curled edges rest on the floor and the middle rises, on a line the paper curls away'),default=5,min=-50,max=50,soft_min=-20,soft_max=20,precision=2,subtype='PERCENTAGE',update=maximum_lift_changed)
    lift_random:BoolProperty(name=_T('Random Lift per Poster'),default=False,description=_T('Each poster lifts a random amount between the minimum and the maximum'))
    lift_min_percent:FloatProperty(name=_T('Minimum Lift (%)'),description=_T('Minimum lift as a ratio of the poster height. Each poster lifts randomly between min and max. Set min negative and max positive to mix forward and backward bends.'),default=.75,min=-50,max=50,soft_min=-20,soft_max=20,precision=2,subtype='PERCENTAGE',update=minimum_lift_changed)
    lift_percent_schema:IntProperty(default=0,options={'HIDDEN'})
    lift_seed:IntProperty(name=_T('Lift Random Seed'),default=0,min=0,max=1000000,description=_T('Keeps the layout and changes only the lift.'))
    bend_faces:IntProperty(name=_T('Vertical Divisions'),default=3,min=1,max=40,description=_T('Rows: how many even pieces each paper is cut into from top to bottom. Bends use these lines. The source is unchanged'))
    attach_mode:EnumProperty(name=_T('Attach Mode'),items=_T_items([
        ('EDGE','Edge Lift','Bottom, side and corner edges of paper stuck to the wall lift up'),
        ('TAPE','Taped','Paper taped only at the top: the bottom lifts and the sides bend outward')]),default='EDGE')
    bend_faces_x:IntProperty(name=_T('Horizontal Divisions'),default=3,min=1,max=40,description=_T('Columns: how many even pieces each paper is cut into from left to right. Bends use these lines. The source is unchanged'))
    roll_enabled:BoolProperty(name=_T('Curl like a Sticky Note'),default=False,description=_T('Bends by curl angle instead of height. Above 90° the end rolls up into a curl.'))
    roll_min:FloatProperty(name=_T('Minimum Curl Angle'),default=60,min=0,max=330,precision=0,description=_T('Smallest curl angle (°) when Vary per Poster is on'))
    roll_angle:FloatProperty(name=_T('Curl Angle'),default=150,min=10,max=330,precision=0,description=_T('Curl angle (°) of the most curled poster. With random lift each poster scales between min and max.'))
    tape_position:EnumProperty(name=_T('Tape Position'),items=_T_items([
        ('TOP_CENTER','Top Center',''),('TOP_CORNERS','Top Corners',''),('TOP_EDGE','Full Top',''),('RANDOM','Random','Mix per poster')]),default='TOP_CENTER')
    tape_width:FloatProperty(name=_T('Tape Width'),default=.2,min=.03,max=.45,subtype='FACTOR',description=_T('Width the tape holds, relative to the poster width'))
    tape_side:FloatProperty(name=_T('Side Bend (%)'),default=4,min=0,max=30,precision=1,subtype='PERCENTAGE',description=_T('Maximum bend height of the side edges relative to the width'))
    tape_curve:FloatProperty(name=_T('Bend Curve'),default=2,min=1,max=5,precision=1,description=_T('1 bends evenly from the tape; higher bends mostly at the ends'))
    curl_bottom:BoolProperty(name=_T('Bottom'),default=True,description=_T('The bottom edge lifts'))
    curl_side:BoolProperty(name=_T('Side'),default=False,description=_T('The left or right side lifts (random per poster)'))
    curl_corner:BoolProperty(name=_T('Corner'),default=False,description=_T('A bottom-left or bottom-right corner curls up diagonally'))
    corner_pair:EnumProperty(name=_T('Corner'),items=_T_items([('BOTH','Both','Both bottom corners together'),('ONE','One','Only one corner per poster'),('MIX','Mix','Mix both and one')]),default='BOTH')
    side_pair:EnumProperty(name=_T('Side'),items=_T_items([('BOTH','Both','Left and right lift together'),('ONE','One','Only the left or right side per poster'),('MIX','Mix','Mix both and one per poster')]),default='BOTH')
    curl_mix:BoolProperty(name=_T('Mix Types per Poster'),default=True,description=_T('When on, each poster randomly uses one (sometimes two) of the chosen types. When off, all chosen types apply together'))
    side_band:FloatProperty(name=_T('Side Lift Width'),default=.3,min=.05,max=.9,subtype='FACTOR',description=_T('Portion of the width that bends from the side'))
    corner_size:FloatProperty(name=_T('Corner Size'),default=.3,min=.05,max=.9,subtype='FACTOR',description=_T('Portion of the short side that folds at the corner'))
    bend_start:FloatProperty(name=_T('Lift Start'),default=.65,min=.01,max=.95,subtype='FACTOR',description=_T('Where the paper starts to bend, top 0 to bottom 1. Everything above stays flat on the wall (for a sticky note: its glue strip)'))
    curl_shape:FloatProperty(name=_T('Curve Shape'),default=2.0,min=1.0,max=5.0,description=_T('How the bottom bends: 1 = straight ramp from the bend line, 2 = even curve, higher = stays flat longer and curls at the tip (sticky note)'))
    cached_topology:StringProperty(default='',options={'HIDDEN'})
    cached_sources:StringProperty(default='',options={'HIDDEN'})
    allow_overlap:BoolProperty(name=_T('Allow Overlap'),default=False,description=_T('Let posters cover each other a little (Random and Fill Gaps). Overlap Grid and Along Rail always overlap'))
    press_strength:FloatProperty(name=_T('Press Strength'),default=.5,min=0,max=1,subtype='FACTOR',description=_T('How hard covered papers are pressed flat. Up to 0.4 flattens the covered parts; above that, any covered paper is pressed as a whole and is completely flat at 1.'))
    press_falloff:FloatProperty(name=_T('Weaker with Depth'),default=1,min=0,max=1,subtype='FACTOR',description=_T('How much pressing weakens the deeper a paper is buried. 1 is the same at any depth; lower keeps the original shape of deep papers.'))
    press:BoolProperty(name=_T('Press Flat When Covered'),default=True,description=_T('Papers covered by other papers are pressed against the wall, removing lift and tilt, so upper papers never float. (Includes other scatter areas stacked on top)'))
    overlap_ratio:FloatProperty(name=_T('Max Overlap Ratio'),description=_T('Maximum overlap allowed, relative to the smaller poster area.'),default=.15,min=0,max=.8,subtype='FACTOR')
    overlap_depth:FloatProperty(name=_T('Overlap Depth Gap'),description=_T('Gap between overlapping surfaces. Tilted or lifted papers get extra height so they never intersect.'),default=.0002,min=.00001,max=.01,subtype='DISTANCE',precision=4)
    manual:CollectionProperty(type=PS_Placement)
    pin_on:BoolProperty(name=_T('Tape & Objects'),default=False,description=_T('Stick your own tape, pins or other objects onto every poster'))
    pin_collection:PointerProperty(name=_T('Tape / Object Collection'),type=bpy.types.Collection,description=_T('A collection with your tapes or objects. Model each lying flat (XY), +Z away from the wall, origin where it touches the paper. One is picked at random per spot'))
    pin_source:EnumProperty(name=_T('Source'),items=_T_items([('COLLECTION','Collection','Pick at random from a collection of tapes / objects','OUTLINER_COLLECTION',0),
                                                ('OBJECT','Object','Use one object you choose (e.g. a clothespin)','OBJECT_DATA',1)]),default='COLLECTION')
    pin_object:PointerProperty(name=_T('Tape / Object'),type=bpy.types.Object,poll=lambda self,o:o.type in {'MESH','CURVE','FONT','SURFACE','META','EMPTY'} and not o.poster_scatter.enabled,
                               description=_T('The one object put on every poster. Origin = where it touches / grips the paper'))
    pin_place:EnumProperty(name=_T('Where'),items=_T_items([('PIVOT','Pivot','On each poster\'s pivot (origin), e.g. a tape at the top center'),('TOP','Top','Random spots along the top edge'),
                                              ('CORNER','Corners','Across the corners, diagonally (like taped-up posters)'),('RANDOM','Random','Random spots anywhere on the paper'),
                                              ('NATURAL','Natural','Each poster is held one way only (all tape, or all pins) and how many depends on its size: small ones often 1, big ones 2 to 4. Kind = object name before _ (TAPE_..., PIN_...) or a pin_kind property')]),default='PIVOT')
    pin_tape_share:FloatProperty(name=_T('Tape Share'),default=.7,min=0.,max=1.,subtype='FACTOR',description=_T('Natural: share of posters held with tape; the rest use the other kinds (pins...). Big posters lean a bit more to pins'))
    pin_corners:EnumProperty(name=_T('Corners'),items=_T_items([('TOP','Top Two','Both top corners'),('ALL','All Four','Every corner'),('RANDOM','Random','Each corner by chance (some posters get one, some two...)')]),default='TOP')
    pin_corner_chance:FloatProperty(name=_T('Corner Chance'),default=.55,min=0.,max=1.,subtype='FACTOR',description=_T('Random corners: chance for each corner to get one'))
    pin_corner_inset:FloatProperty(name=_T('Inset'),default=.004,min=0.,max=.1,subtype='DISTANCE',unit='LENGTH',description=_T('How far in from the very corner the tape sits (0 = centred on the corner)'))
    pin_skip_lifted:BoolProperty(name=_T('Skip Lifted Spots'),default=True,description=_T('No tape / object where the paper is lifted off what is under it (curled corners, bent bottoms): it would not stick there'))
    pin_max_lift:FloatProperty(name=_T('Max Gap'),default=.003,min=0.,max=.1,subtype='DISTANCE',unit='LENGTH',description=_T('Paper lifted more than this off the wall / paper below counts as lifted'))
    pin_count:IntProperty(name=_T('Per Poster'),default=1,min=1,max=8,description=_T('How many per poster (random placements)'))
    pin_chance:FloatProperty(name=_T('Chance'),default=1.,min=0.,max=1.,subtype='FACTOR',description=_T('Share of posters that get one. 1 = all of them'))
    pin_follow:BoolProperty(name=_T('Turn with Poster'),default=True,description=_T('On: turns with the poster rotation (pick the axes with X Y Z). Off: stays upright'))
    pin_follow_x:BoolProperty(name=_T('X'),default=True,description=_T('Follow the poster X rotation (tilt forward / back)'))
    pin_follow_y:BoolProperty(name=_T('Y'),default=True,description=_T('Follow the poster Y rotation (side lean)'))
    pin_follow_z:BoolProperty(name=_T('Z'),default=True,description=_T('Follow the poster Z rotation (turn on the wall)'))
    pin_spin:FloatProperty(name=_T('Random Turn'),default=0.,min=0.,max=math.pi,subtype='ANGLE',description=_T('Extra random turn per object'))
    pin_scale:FloatProperty(name=_T('Size'),default=1.,min=.01,max=20.,description=_T('Size of the objects (1 = as modeled)'))
    pin_scale_random:FloatProperty(name=_T('Random Size'),default=0.,min=0.,max=.9,subtype='FACTOR',description=_T('Each one a bit bigger or smaller'))
    pin_poster_scale:BoolProperty(name=_T('Match Poster Size'),default=True,description=_T('Also scale with the poster (Scale and Random Scale)'))
    pin_seed:IntProperty(name=_T('Seed'),default=0,min=0,description=_T('Different random picks and spots'))
    pin_offset:FloatProperty(name=_T('Lift Off Paper'),default=.0002,min=0.,max=.05,subtype='DISTANCE',description=_T('Small gap so the objects do not flicker with the paper'))
    pin_output:PointerProperty(type=bpy.types.Object)
    manual_poster:PointerProperty(name=_T('Poster to Place'),type=bpy.types.Object,description=_T('The poster to pin by clicking on the wall'))
    manual_angle:FloatProperty(name=_T('Place Angle'),default=0,subtype='ANGLE',description=_T('Starting angle for the next pinned poster (R while placing rotates it)'))
    manual_no_lift:BoolProperty(name=_T('Place Without Lift'),default=False,description=_T('When on, newly placed posters stick flat without lift or bend'))
    manual_scale:FloatProperty(name=_T('Place Scale'),default=1,min=.05,max=20,soft_min=.1,soft_max=5,step=5,precision=2,
                               description=_T('Scale factor for the poster to place. You can also change it with S or +/- while placing.'))
    repeat:BoolProperty(name=_T('Reuse Posters'),default=False,update=repeat_changed,description=_T('Use each poster more than once, to fill large areas'))
    repeat_limited:BoolProperty(name=_T('Limit Copies by Size'),default=True,description=_T('Cap how many copies each poster gets, by poster size. Off repeats freely'))
    repeat_ranges:CollectionProperty(type=PS_RepeatRange)
    live:BoolProperty(name=_T('Live Preview'),default=True,description=_T('Applies paint and setting changes about every 0.4 seconds. Many posters take longer to compute.'))
    paint_step:FloatProperty(name=_T('Paint Detail'),default=.1,min=.02,max=.5,subtype='DISTANCE',description=_T('Spacing of the paintable grid on new areas. Smaller paints finer but is heavier'))
    check_step:FloatProperty(default=.05,min=.01)
    status:StringProperty(default='Pick a poster collection, then press Reload.')

class PS_OT_repeat_range(bpy.types.Operator):
    bl_idname='poster_scatter.repeat_range';bl_label=_T('Edit Repeat Range');bl_options={'UNDO'}
    action:EnumProperty(items=_T_items([('ADD','Add',''),('REMOVE','Remove','')]))
    index:IntProperty(default=-1)
    def execute(self,context):
        area=current(context)
        if not area:return {'CANCELLED'}
        s=area.poster_scatter;ensure_repeat_ranges(s);rules=s.repeat_ranges
        if self.action=='ADD':
            if len(rules)>=12:self.report({'INFO'},_T('Up to 12 ranges can be set.'));return {'CANCELLED'}
            widths=[r.upper-(rules[i-1].upper if i else 0.) for i,r in enumerate(rules)]
            idx=max(range(len(rules)),key=lambda i:widths[i])
            if widths[idx]<.0002:return {'CANCELLED'}
            lower=rules[idx-1].upper if idx else 0.;upper=rules[idx].upper;limit=rules[idx].limit
            rules[idx]['upper']=(lower+upper)/2
            rule=rules.add();rule['upper']=upper;rule.limit=limit;rules.move(len(rules)-1,idx+1)
        elif len(rules)>1 and 0<=self.index<len(rules):
            rules.remove(self.index);rules[-1]['upper']=1.
        return {'FINISHED'}


class PS_OT_create(bpy.types.Operator):
    bl_idname='poster_scatter.create';bl_label=_T('Scatter Posters');bl_options={'UNDO'}
    bl_description=_T('Make a scatter area on the selected wall or floor. Edit Mode uses the selected faces, Object Mode uses all faces. Poles and curved walls work too')
    def execute(self,context):
        try:
            if not context.object:raise ValueError('Please select a wall or floor.')
            target=context.object;faces=target.mode=='EDIT';area=create_area(context,target,faces)
            mark_face_area(area,target,faces)
            st=area.poster_scatter;st.source_surface=target;st.hide_source=False if faces else context.scene.poster_scatter_setup.hide_source
            if context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
            for o in context.selected_objects:o.select_set(False)
            area.select_set(True);context.view_layer.objects.active=area
            n=len(st.output.data.vertices) if st.output else 0
            if not st.collection:self.report({'WARNING'},_T('Scatter made. Pick a poster collection in the panel to place posters.'))
            else:self.report({'INFO'},_T('Placed %d poster%s on %s. Adjust them in the panel.'%(n,'' if n==1 else 's',target.name)))
            return {'FINISHED'}
        except Exception as exc:self.report({'ERROR'},_T(str(exc)));return {'CANCELLED'}


LAYER_SKIP={'output','cache','render_cache','pin_output','stack_on','manual','manual_poster','rna_type','build_id','status'}


def add_layer(context,area,collection=None,mode='FILL',count=None):
    """New scatter on the same faces, resting on the top layer of this stack. Press again for layer 3, 4, ...
    collection: the posters for the new layer (own paper look and lighting per batch); None = same as below."""
    base=stack_top(area);s0=base.poster_scatter
    root=(stack_chain(base) or [base])[-1];n=len(stack_chain(base))+2
    new=area.copy();new.data=area.data.copy();new.name='%s · Layer %d'%(root.name,n)
    for c in area.users_collection:c.objects.link(new)
    s=new.poster_scatter
    for k in ('output','cache','render_cache','pin_output','stack_on'):setattr(s,k,None)   # First, so no update below writes into the original's result
    for k in [k for k in s.keys() if k in ('ps_frozen','ps_frozen_key','ps_note','ps_skipped')]:del s[k]
    for p in s0.bl_rna.properties:   # Same look as the layer below (the copy came from the picked area)
        k=p.identifier
        if k in LAYER_SKIP or p.is_readonly or p.type=='COLLECTION':continue
        try:setattr(s,k,getattr(s0,k))
        except Exception:pass
    s.manual.clear();s.seed=s0.seed+101*n;s.status=''
    out=bpy.data.objects.new('Poster Scatter Result · '+new.name.replace('Poster Scatter Area · ',''),bpy.data.meshes.new('Poster Scatter Points'))
    for c in (s0.output.users_collection if s0.output else area.users_collection):c.objects.link(out)
    out.parent=new;out['ps_owned']=True;s.output=out;out.hide_viewport=not getattr(context.scene,'ps_show_results',True)
    out.modifiers.new('Poster Scatter','NODES').node_group=make_node()
    new.location+=new.matrix_world.to_3x3().col[2].normalized()*.0001   # Keep each layer's faces apart from the one below
    ps_area_invisible(new)
    if collection is not None:s.collection=collection
    if count:s.count_auto=False;s.count=count
    s.stack_mode=mode;s['ps_was_stacked']=True   # Keep the chosen mode when stack_on is set below
    if s.collection:refresh_sources(new)
    s.stack_on=base   # Places the posters (update)
    return new,n


class PS_OT_add_layer(bpy.types.Operator):
    bl_idname='poster_scatter.add_layer';bl_label=_T('Add Layer');bl_options={'UNDO'}
    bl_description=_T('Add another scatter on the same wall, on top of this stack. It fills the empty space around the posters below (or lies over them, see With Posters Below). Press again for more layers')
    collection_name:StringProperty(name=_T('Posters'),description=_T('Poster collection for the new layer. Use a separate batch per paper kind so each keeps its own crumple, gloss and lighting'))
    mode:EnumProperty(name=_T('With Posters Below'),items=_T_items([('FILL','Fill Empty Space','Only where the layers below have no posters'),('TOP','Stack on Top','Over the layers below')]),default='FILL')
    count:IntProperty(name=_T('Count'),default=20,min=1,max=1500)
    @classmethod
    def poll(cls,context):
        a=current(context);return a is not None and a.poster_scatter.layout!='RAIL' and area_flat(a.data) is None
    def invoke(self,context,event):
        a=current(context);s=a.poster_scatter
        if not self.collection_name or self.collection_name not in bpy.data.collections:self.collection_name=s.collection.name if s.collection else ''
        self.count=max(1,s.count)
        return context.window_manager.invoke_props_dialog(self,width=360,title=_T('Add Layer'),confirm_text='Add Layer')
    def draw(self,context):
        l=self.layout
        l.prop_search(self,'collection_name',bpy.data,'collections',text=_T('Posters'),icon='OUTLINER_COLLECTION')
        l.prop(self,'count')
        l.row().prop(self,'mode',expand=True)
        l.label(text=_T('Tip: one batch per paper kind keeps its own look'),icon='INFO')
    def execute(self,context):
        try:
            col=bpy.data.collections.get(self.collection_name) if self.collection_name else None
            new,n=add_layer(context,current(context),col,self.mode,self.count)
            for o in context.selected_objects:o.select_set(False)
            try:new.hide_set(False);new.select_set(True)
            except RuntimeError:pass
            context.view_layer.objects.active=new
            k=len(new.poster_scatter.output.data.vertices) if new.poster_scatter.output else 0
            self.report({'INFO'},_T('Layer %d: placed %d poster%s %s'%(n,k,'' if k==1 else 's','in the empty space' if self.mode=='FILL' else 'on top')))
            return {'FINISHED'}
        except Exception as exc:self.report({'ERROR'},_T(str(exc)));return {'CANCELLED'}


def ps_bake_area(context,area,keep=True):
    s=area.poster_scatter;res=s.output
    if not res:raise ValueError('No scatter result on '+area.name)
    if getattr(s,'live',False):s.live=False
    new=res.copy();new.data=res.data.copy()
    for k in ('ps_owned',):
        if k in new.keys():del new[k]
    mw=res.matrix_world.copy();new.parent=None;new.matrix_world=mw
    tgt=getattr(s,'source_surface',None)
    new.name='Poster Mesh · '+(tgt.name if tgt else area.name)
    for col in res.users_collection:col.objects.link(new)
    new.hide_render=False;new.hide_viewport=False
    vl=context.view_layer
    try:new.hide_set(False)
    except RuntimeError:pass
    g=bpy.data.node_groups.get('PS Realize')
    if not g:
        g=bpy.data.node_groups.new('PS Realize','GeometryNodeTree')
        g.interface.new_socket('Geometry',in_out='INPUT',socket_type='NodeSocketGeometry')
        g.interface.new_socket('Geometry',in_out='OUTPUT',socket_type='NodeSocketGeometry')
        gi=g.nodes.new('NodeGroupInput');go=g.nodes.new('NodeGroupOutput');rz=g.nodes.new('GeometryNodeRealizeInstances')
        g.links.new(gi.outputs[0],rz.inputs[0]);g.links.new(rz.outputs[0],go.inputs[0])
    md=new.modifiers.new('PS Realize','NODES');md.node_group=g
    vl.update()
    dg=context.evaluated_depsgraph_get();dg.update()
    me=bpy.data.meshes.new_from_object(new.evaluated_get(dg),preserve_all_data_layers=True,depsgraph=dg)
    old=new.data;new.modifiers.clear();new.data=me;me.name=new.name
    if old.users==0:bpy.data.meshes.remove(old)
    if len(me.polygons)==0:
        bpy.data.objects.remove(new,do_unlink=True)
        raise ValueError('Nothing to convert on '+area.name+' (no posters placed?)')
    pin=s.pin_output if s.pin_output and len(s.pin_output.data.vertices) else None
    if pin is not None:   # tapes / objects become a real mesh next to the posters
        pn=pin.copy();pn.data=pin.data.copy();pn.parent=None;pn.matrix_world=pin.matrix_world.copy()
        if 'ps_owned' in pn.keys():del pn['ps_owned']
        pn.name='Poster Attachments · '+(tgt.name if tgt else area.name)
        for col in pin.users_collection:col.objects.link(pn)
        pn.hide_viewport=False;pn.modifiers.new('PS Realize','NODES').node_group=g;vl.update();dg=context.evaluated_depsgraph_get();dg.update()
        pm=bpy.data.meshes.new_from_object(pn.evaluated_get(dg),preserve_all_data_layers=True,depsgraph=dg);po=pn.data;pn.modifiers.clear();pn.data=pm;pm.name=pn.name
        if po.users==0:bpy.data.meshes.remove(po)
        pn.parent=new;pn.matrix_parent_inverse=new.matrix_world.inverted()
    if keep:
        for o in (area,res)+((pin,) if pin is not None else ()):
            o.hide_render=True
            try:o.hide_set(True)
            except RuntimeError:pass
        area['ps_baked']=new.name
    else:
        if pin is not None:bpy.data.objects.remove(pin,do_unlink=True)
        bpy.data.objects.remove(res,do_unlink=True);bpy.data.objects.remove(area,do_unlink=True)
    return new


class PS_OT_bake(bpy.types.Operator):
    bl_idname='poster_scatter.bake';bl_label=_T('Convert to Mesh');bl_options={'UNDO'}
    bl_description=_T('Turn the placed posters into a real mesh (final, no longer editable by the addon). The scatter setup is kept hidden as a backup unless Keep Backup is off')
    keep:BoolProperty(name=_T('Keep Backup'),default=True,description=_T('Keep the original scatter hidden so it can be edited again later'))
    def execute(self,context):
        if context.mode!='OBJECT':
            try:bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:pass
        areas=[]
        for o in list(context.selected_objects)+[context.object]:
            if not o:continue
            a=o if o.poster_scatter.enabled else (o.parent if o.parent and o.parent.poster_scatter.enabled else None)
            if a and a not in areas:areas.append(a)
        if not areas:self.report({'WARNING'},_T('Select a scatter area or its result'));return {'CANCELLED'}
        made=[]
        try:
            for a in areas:made.append(ps_bake_area(context,a,self.keep))
        except Exception as exc:self.report({'ERROR'},_T(str(exc)));return {'CANCELLED'}
        for o in context.selected_objects:
            try:o.select_set(False)
            except RuntimeError:pass
        for n in made:
            try:n.select_set(True)
            except RuntimeError:pass
        if made:context.view_layer.objects.active=made[-1]
        self.report({'INFO'},_T('Converted %d scatter(s) to mesh: '%len(made)+', '.join(n.name for n in made)))
        return {'FINISHED'}

class PS_OT_update(bpy.types.Operator):
    bl_idname='poster_scatter.update';bl_label=_T('Update Scatter');bl_description=_T('Recalculate the scatter with the current settings (stays editable)');bl_options={'UNDO'}
    reload:BoolProperty(default=False)
    def execute(self,context):
        a=current(context)
        if not a:return {'CANCELLED'}
        try:
            if self.reload or not a.poster_scatter.cache:refresh_sources(a)
            rebuild(a);SIGNATURES[a.as_pointer()]=signature(a);return {'FINISHED'}
        except Exception as exc:self.report({'ERROR'},_T(str(exc)));return {'CANCELLED'}

class PS_OT_place(bpy.types.Operator):
    bl_idname='poster_scatter.place';bl_label=_T('Click Wall to Place');bl_options={'UNDO'}
    bl_description=_T('Click on the wall to place. While placing: R rotate · S scale (then X width / Y or Z height) · +/- scale 10% · Ctrl snap · Esc cancel')
    index:IntProperty(default=-1,options={'HIDDEN','SKIP_SAVE'})
    area_name:StringProperty(options={'HIDDEN','SKIP_SAVE'})
    def invoke(self,context,event):
        self.area_obj=bpy.data.objects.get(self.area_name) if self.area_name else current(context)
        self.offset=Vector((0.,0.))
        if not self.area_obj:self.report({'WARNING'},_T('Select a scatter first.'));return {'CANCELLED'}
        if context.area is None or context.area.type!='VIEW_3D':self.report({'WARNING'},_T('Use Click Wall to Place from the 3D View sidebar.'));return {'CANCELLED'}
        s=self.area_obj.poster_scatter
        if PLACERS:self.report({'WARNING'},_T('Finish the current placement first.'));return {'CANCELLED'}
        if self.index>=0:   # Re-place already placed posters
            if self.index>=len(s.manual) or not s.manual[self.index].poster:return {'CANCELLED'}
            item=s.manual[self.index];self.original=item.poster;self.angle=item.angle;self.k=item.scale;self.kx=item.sx;self.ky=item.sy
        else:
            if not s.manual_poster or s.manual_poster not in sources(s.collection):
                self.report({'ERROR'},_T('Please choose a poster from the poster collection to place.'));return {'CANCELLED'}
            self.original=s.manual_poster;self.angle=s.manual_angle;self.k=s.manual_scale;self.kx=self.ky=1.
        if not s.cache:refresh_sources(self.area_obj)
        self.source=next((o for o in s.cache.objects if o.get('source')==self.original.name),None)
        if self.source is None:self.report({'ERROR'},_T('Press Reload Collection Sources.'));return {'CANCELLED'}
        self.area=context.area;self.region=next(r for r in self.area.regions if r.type=='WINDOW');self.rv3d=self.area.spaces.active.region_3d
        self.handler=None;self.candidate=None;self.valid=False;self.closed=False;self.hit=None
        self.mode='MOVE';self.mode_start=None
        mesh=self.area_obj.data;mesh.calc_loop_triangles()
        self.smap=SurfaceMap(mesh) if area_flat(mesh) is not None else None
        self.tree=self.smap.flat if self.smap else BVHTree.FromPolygons([v.co for v in mesh.vertices],[tuple(t.vertices) for t in mesh.loop_triangles],all_triangles=True)
        self.handler=bpy.types.SpaceView3D.draw_handler_add(self.draw_overlay,(),'WINDOW','POST_VIEW')
        self.locate(event)
        if self.area_name and self.index>=0 and self.candidate:   # Grabbed from the wall: keep the poster where it is under the cursor
            item=s.manual[self.index];self.offset=Vector((item.x-self.candidate[0],item.y-self.candidate[1]));self.update_candidate()
        self.header()
        PLACERS.append(self);context.window_manager.modal_handler_add(self);return {'RUNNING_MODAL'}

    def header(self):
        what='Place Again' if self.index>=0 else 'Place Poster'
        if self.mode=='ROTATE':tip='Rotate: move mouse left/right · Shift fine · Ctrl 15° steps · Click/R/Enter confirm · Esc revert'
        elif self.mode=='SCALE':
            ax_=getattr(self,'scale_axis',None)
            tip=('Scale %s with mouse'%{'X':'WIDTH (X)','Y':'HEIGHT (Y/Z)'}[ax_] if ax_ else 'Scale with mouse')+(' (left smaller / right bigger)' if getattr(self,'scale_horiz',False) else ' (toward / away from center)')+(' · X width / Y or Z height' if not ax_ else '')+' · Shift fine · Ctrl 5% steps · Click/S/Enter confirm · Esc revert'
        else:tip='Left click place · R rotate · S scale (then X / Y / Z for one axis) · +/- scale 10% · 0 reset · Esc cancel'
        extra=(' · W %d%% · H %d%%'%(round(self.kx*100),round(self.ky*100))) if (abs(self.kx-1)>1e-3 or abs(self.ky-1)>1e-3) else ''
        self.area.header_text_set('%s  [angle %.0f° · scale %d%%%s]  %s'%(what,math.degrees(self.angle),round(self.k*100),extra,tip))

    def sample(self,x,y):
        hit=self.tree.ray_cast(Vector((x,y,1)),Vector((0,0,-1)),2)
        return ([1],None,None) if hit[0] is not None else None

    def locate(self,event):
        from bpy_extras import view3d_utils
        p=(event.mouse_x-self.region.x,event.mouse_y-self.region.y)
        origin=view3d_utils.region_2d_to_origin_3d(self.region,self.rv3d,p)
        direction=view3d_utils.region_2d_to_vector_3d(self.region,self.rv3d,p)
        inverse=self.area_obj.matrix_world.inverted();origin=inverse@origin;direction=inverse.to_3x3()@direction
        if self.smap:   # Curved surface: hit the real surface and convert to unfolded coordinates
            loc,_,idx,_=self.smap.surface.ray_cast(origin,direction.normalized())
            if idx is None:self.hit=None;self.candidate=None;return
            self.hit=self.smap.to_flat(idx,loc);self.update_candidate();return
        if abs(direction.z)<1e-9:self.hit=None;self.candidate=None;return
        t=-origin.z/direction.z
        if t<0:self.hit=None;self.candidate=None;return
        self.hit=origin+direction*t;self.update_candidate()

    def update_candidate(self):
        if self.hit is None:self.candidate=None;return
        s=self.area_obj.poster_scatter;sc=s.scale*self.k;hit=self.hit
        center=Matrix.Rotation(self.angle,3,'Z')@Vector((self.source['center_x']*sc*self.kx,self.source['center_y']*sc*self.ky,0))
        x,y=hit.x+center.x+self.offset.x,hit.y+center.y+self.offset.y
        self.candidate=(x,y,self.original,self.angle,self.k)
        w,h=self.source['width']*sc*self.kx,self.source['height']*sc*self.ky
        self.box=rectangle(x,y,w,h,self.angle)
        self.valid=footprint_fits(self.sample,x,y,w,h,self.angle,s.check_step)
        if self.valid:
            # Already placed automatic instances are replaced around this pinned poster.
            catalog={o['source']:o for o in s.cache.objects};others=[]
            margin=0 if s.allow_overlap else s.gap
            for n,item in enumerate(s.manual):
                if n==self.index:continue
                obj=catalog.get(item.poster.name) if item.poster else None
                k=item.scale
                if obj:others.append(rectangle(item.x,item.y,obj['width']*s.scale*k*item.sx+margin,obj['height']*s.scale*k*item.sy+margin,item.angle))
            self.valid=placement_clear(rectangle(x,y,w+margin,h+margin,self.angle),others,s)

    def pivot_2d(self):
        from bpy_extras import view3d_utils
        s=self.area_obj.poster_scatter
        if self.smap:p,n=self.smap.map(self.hit.x,self.hit.y);local=p+n*s.offset
        else:local=Vector((self.hit.x,self.hit.y,s.offset))
        return view3d_utils.location_3d_to_region_2d(self.region,self.rv3d,self.area_obj.matrix_world@local)

    def begin(self,mode,event):
        if self.hit is None:return
        piv=self.pivot_2d()
        if piv is None:return
        m=Vector((event.mouse_x-self.region.x,event.mouse_y-self.region.y))
        self.mode=mode;self.mode_start=(piv,m-piv,self.angle,self.k);self.scale_axis=None;self.stretch_start=(self.kx,self.ky);self.mouse0=m;self._fine=.2 if event.shift else 1.;self.mode_orig=(self.angle,self.k,self.kx,self.ky)
        self.scale_horiz=(m-piv).length<60   # Started on the pivot: no distance to shrink, so scale by left/right travel

    def drag(self,event):
        m=Vector((event.mouse_x-self.region.x,event.mouse_y-self.region.y))
        fine=.2 if event.shift else 1.   # Shift: 5x finer, like Blender
        if getattr(self,'_fine',fine)!=fine:   # Shift pressed/released mid-drag: continue from the current value, no jump
            piv=self.mode_start[0];self.mode_start=(piv,m-piv,self.angle,self.k);self.stretch_start=(self.kx,self.ky);self.mouse0=m
        self._fine=fine
        piv,d0,a0,k0=self.mode_start;d=m-piv
        if self.mode=='ROTATE':   # Horizontal mouse travel turns the poster (stable even close to its center): 100 px = 20°
            dx=m.x-getattr(self,'mouse0',m).x
            a=a0-math.radians(.2)*dx*fine
            if event.ctrl:a=round(a/math.radians(15))*math.radians(15)
            self.angle=math.atan2(math.sin(a),math.cos(a))
        else:
            # Growing: calm and linear, 300 px away from the start distance adds 100 % (never faster than that).
            # Shrinking: proportional to the distance, so moving onto the pivot always reaches the smallest size
            # (the linear rule stopped at 1 - start/300, e.g. only 50 % when the drag began 150 px from the pivot)
            # S pressed with the mouse on the poster's pivot (the usual case while placing): there is no distance
            # to shrink, so use left/right travel instead: 250 px right = x2, 250 px left = x0.5
            if getattr(self,'scale_horiz',False):r=2.**((m.x-getattr(self,'mouse0',m).x)/250.*fine)
            elif d.length>=d0.length:r=1+(d.length-d0.length)/max(d0.length,300.)*fine
            else:r=1-(1-d.length/max(d0.length,1e-6))*fine
            r=max(.05,r);ax_=getattr(self,'scale_axis',None)
            sx0,sy0=getattr(self,'stretch_start',(self.kx,self.ky))
            if ax_=='X':self.k=k0;self.ky=sy0;v=sx0*r
            elif ax_=='Y':self.k=k0;self.kx=sx0;v=sy0*r
            else:self.kx,self.ky=sx0,sy0;v=k0*r
            if event.ctrl:v=round(v/.05)*.05
            v=max(.05,min(20.,v))
            if ax_=='X':self.kx=v
            elif ax_=='Y':self.ky=v
            else:self.k=v

    def draw_overlay(self):
        if self.closed or not self.candidate or bpy.context.area!=self.area:return
        import gpu
        from gpu_extras.batch import batch_for_shader
        s=self.area_obj.poster_scatter;mw=self.area_obj.matrix_world
        if self.smap:   # Draw the box outline along the curvature
            def put(x,y):
                p,n=self.smap.map(x,y);return tuple(mw@(p+n*s.offset))
            points=[put(p.x,p.y) for p in self.box]
            outline=[put(a.x+(b.x-a.x)*t/12,a.y+(b.y-a.y)*t/12) for a,b in zip(self.box,self.box[1:]+self.box[:1]) for t in range(12)]
        else:
            points=[tuple(mw@Vector((p.x,p.y,s.offset))) for p in self.box];outline=points
        shader=gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.depth_test_set('NONE');gpu.state.line_width_set(2)
        color=(.2,1,.5,1) if self.valid else (1,.5,.1,1)
        shader.bind();shader.uniform_float('color',color)
        batch_for_shader(shader,'LINE_STRIP',{'pos':outline+[outline[0]]}).draw(shader)
        # Top-edge marker (to show rotation): thick line between the two top corners
        top=sorted(range(4),key=lambda i:-(Matrix.Rotation(-self.angle,3,'Z')@Vector((self.box[i].x-self.candidate[0],self.box[i].y-self.candidate[1],0))).y)[:2]
        gpu.state.line_width_set(5);batch_for_shader(shader,'LINES',{'pos':[points[top[0]],points[top[1]]]}).draw(shader)
        gpu.state.line_width_set(1)

    def finish(self):
        if self.closed:return
        self.closed=True
        if self.handler:bpy.types.SpaceView3D.draw_handler_remove(self.handler,'WINDOW');self.handler=None
        self.area.header_text_set(None);self.area.tag_redraw()
        if self in PLACERS:PLACERS.remove(self)

    def commit(self):
        if not self.candidate or not self.valid:
            self.report({'WARNING'},_T('Place it inside the area. Also check overlaps with other manually placed posters.'));return False
        s=self.area_obj.poster_scatter;x,y,poster,angle,k=self.candidate
        if self.index>=0:
            item=s.manual[self.index];old=(item.x,item.y,item.angle,item.scale,item.sx,item.sy)
        else:item=s.manual.add();old=None
        item.poster=poster;item.x,item.y,item.angle,item.scale=x,y,angle,k;item.sx,item.sy=self.kx,self.ky
        if old is None:item.no_lift=s.manual_no_lift
        # Once placed, the automatic posters follow the layout rules again around it (no covering by the manual poster).
        # They were only held still while dragging (click-to-grab freeze).
        for key in ('ps_frozen_key','ps_frozen'):
            if key in s:del s[key]
        try:rebuild(self.area_obj);SIGNATURES[self.area_obj.as_pointer()]=signature(self.area_obj)
        except Exception as exc:
            if old:item.x,item.y,item.angle,item.scale,item.sx,item.sy=old
            else:s.manual.remove(len(s.manual)-1)
            self.report({'ERROR'},_T(str(exc)));return None
        if self.index<0:s.manual_angle=angle;s.manual_scale=k   # Next placement uses the same angle and size
        return True

    def modal(self,context,event):
        if self.closed:return {'CANCELLED'}
        t,v=event.type,event.value
        if self.mode!='MOVE':
            if t in {'ESC','RIGHTMOUSE'} and v=='PRESS':
                self.angle,self.k,self.kx,self.ky=getattr(self,'mode_orig',(self.angle,self.k,self.kx,self.ky));self.mode='MOVE'
            elif self.mode=='SCALE' and t in {'X','Y','Z'} and v=='PRESS':   # Blender style: S then X (width) / Y or Z (height); same key again = all
                want='X' if t=='X' else 'Y'
                self.scale_axis=None if getattr(self,'scale_axis',None)==want else want
                self.drag(event)
            elif (t in {'RET','NUMPAD_ENTER'} or (t=='R' and self.mode=='ROTATE') or (t=='S' and self.mode=='SCALE')) and v=='PRESS':self.mode='MOVE'
            elif t in {'R','S'} and v=='PRESS':self.begin('ROTATE' if t=='R' else 'SCALE',event)
            elif t=='LEFTMOUSE' and v=='PRESS':
                self.update_candidate();r=self.commit()
                if r is None:self.finish();return {'CANCELLED'}
                if r:self.finish();return {'FINISHED'}
                self.mode='MOVE'
            elif t in {'MOUSEMOVE','LEFT_CTRL','RIGHT_CTRL','LEFT_SHIFT','RIGHT_SHIFT'}:self.drag(event)
            else:return {'RUNNING_MODAL'}
            self.update_candidate();self.header();self.area.tag_redraw();return {'RUNNING_MODAL'}
        if t in {'ESC','RIGHTMOUSE'} and v=='PRESS':
            self.finish()
            s=self.area_obj.poster_scatter   # Cancelled: the others are no longer held in place either
            if 'ps_frozen_key' in s or 'ps_frozen' in s:
                for key in ('ps_frozen_key','ps_frozen'):
                    if key in s:del s[key]
                try:rebuild(self.area_obj);SIGNATURES[self.area_obj.as_pointer()]=signature(self.area_obj)
                except Exception as exc:self.report({'WARNING'},_T(str(exc)))
            return {'CANCELLED'}
        if t in {'R','S'} and v=='PRESS':
            self.begin('ROTATE' if t=='R' else 'SCALE',event);self.header();return {'RUNNING_MODAL'}
        if t in {'NUMPAD_PLUS','EQUAL','NUMPAD_MINUS','MINUS'} and v=='PRESS':
            self.k=max(.05,min(20.,self.k*(1.1 if t in {'NUMPAD_PLUS','EQUAL'} else 1/1.1)))
            self.update_candidate();self.header();self.area.tag_redraw();return {'RUNNING_MODAL'}
        if t in {'ZERO','NUMPAD_0'} and v=='PRESS':
            self.angle=0.;self.k=1.;self.kx=self.ky=1.;self.update_candidate();self.header();self.area.tag_redraw();return {'RUNNING_MODAL'}
        if t in {'MOUSEMOVE','LEFTMOUSE'}:
            self.locate(event);self.area.tag_redraw()
        if t=='LEFTMOUSE' and v=='PRESS':
            r=self.commit()
            if r is None:self.finish();return {'CANCELLED'}
            if r:self.finish();return {'FINISHED'}
            return {'RUNNING_MODAL'}
        if t in {'MIDDLEMOUSE','WHEELUPMOUSE','WHEELDOWNMOUSE','TRACKPADPAN','TRACKPADZOOM'}:return {'PASS_THROUGH'}
        return {'RUNNING_MODAL'}

RESET_KEYS=('press','press_strength','press_falloff','tilt_random','tilt_min','grid_overlap','grid_jitter','grid_fill','grid_stagger','layout','seed','scale','gap','rotation','yaw','rot_x_on','rot_y_on','rot_z_on','rot_angle','rot_rand','rot_x_angle','rot_x_rand','rot_y_angle','rot_y_rand','rot_z_angle','rot_z_rand','scale_random','offset','tilt','lift_enabled','bottom_lift_percent','lift_random','lift_min_percent',
            'lift_seed','bend_faces','bend_start','curl_shape','side_pair','corner_pair','attach_mode','bend_faces_x','roll_enabled','roll_angle','roll_min','tape_position','tape_width','tape_side','tape_curve','surface_mode','conform_faces','conform_faces_v','curl_bottom','curl_side','curl_corner','curl_mix','side_band','corner_size','allow_overlap','overlap_ratio','overlap_depth','repeat','repeat_limited','count_auto',
            'grid_conform','grid_stiffness','rail_hang','rail_overlap','rail_jitter','rail_drop','rail_drop_random','rail_swing','rail_order','rail_pick','rail_slide','rail_wrap','rail_reverse','pin_on')+PIN_KEYS


CLIP_PROFILE=((-14,.3),(4,.3),(8,1.5),(13,1.5),(17,.9),(56,2.4),(56,6.6),(30,5.9),(13,5.4),(0,5.0),(-9,4.4),(-13,3.3),(-14,1.9))


def clip_material(name,color,metal,rough):
    m=bpy.data.materials.get(name)
    if m:return m
    m=bpy.data.materials.new(name);m.diffuse_color=color+(1.,)
    m.use_nodes=True;b=m.node_tree.nodes.get('Principled BSDF')
    if b:b.inputs['Base Color'].default_value=color+(1.,);b.inputs['Metallic'].default_value=metal;b.inputs['Roughness'].default_value=rough
    m.metallic=metal;m.roughness=rough
    return m


def make_clip_mesh(name='Clothespin'):
    """Wooden clothespin (about 72 mm). Origin = grip point: put the paper's top edge here. +Y = handle up, the two legs sit either side of Z=0."""
    import bmesh
    mm=.001;W=5.;bm=bmesh.new()
    def leg(sign):
        A=[bm.verts.new(Vector((-W*mm,y*mm,sign*z*mm))) for y,z in CLIP_PROFILE]
        B=[bm.verts.new(Vector((W*mm,y*mm,sign*z*mm))) for y,z in CLIP_PROFILE]
        bm.faces.new(A[::-1]);bm.faces.new(B)
        for i in range(len(A)):
            q=(i+1)%len(A);bm.faces.new([A[i],A[q],B[q],B[i]])
    leg(1);leg(-1)
    def box(x0,x1,y0,y1,z0,z1):
        r=bmesh.ops.create_cube(bm,size=1.)
        for v in r['verts']:v.co=Vector(((x0 if v.co.x<0 else x1)*mm,(y0 if v.co.y<0 else y1)*mm,(z0 if v.co.z<0 else z1)*mm))
        for f in {f for v in r['verts'] for f in v.link_faces}:f.material_index=1
    box(-5.9,5.9,13.6,16.4,5.4,6.4);box(-5.9,5.9,13.6,16.4,-6.4,-5.4);box(-6.,-5.,13.6,16.4,-6.4,6.4);box(5.,6.,13.6,16.4,-6.4,6.4)
    bmesh.ops.recalc_face_normals(bm,faces=bm.faces[:])
    me=bpy.data.meshes.new(name);bm.to_mesh(me);bm.free()
    me.materials.append(clip_material('Clothespin · Wood',(.62,.45,.27),0.,.55))
    me.materials.append(clip_material('Clothespin · Steel',(.72,.72,.74),1.,.3))
    return me


class PS_OT_add_clip(bpy.types.Operator):
    bl_idname='poster_scatter.add_clip';bl_label=_T('Add Clothespin');bl_options={'UNDO'}
    bl_description=_T('Make a clothespin object at the 3D cursor and use it on these posters. Move, edit or copy it like any object')
    def execute(self,context):
        a=current(context)
        ob=bpy.data.objects.new('Clothespin',make_clip_mesh());ob.location=context.scene.cursor.location
        (context.collection or context.scene.collection).objects.link(ob)
        if a:
            s=a.poster_scatter;s.pin_source='OBJECT';s.pin_object=ob;s.pin_on=True
            try:rebuild(a)
            except Exception as exc:self.report({'WARNING'},_T(str(exc)))
        self.report({'INFO'},_T('"%s" added at the 3D cursor'%ob.name));return {'FINISHED'}


class PS_OT_sticky_preset(bpy.types.Operator):
    bl_idname='poster_scatter.sticky_preset';bl_label=_T('Sticky Note Lift');bl_options={'UNDO'}
    bl_description=_T('Glue strip at the top stays on the wall, the rest lifts off and curls a little at the bottom, a different amount on each note')
    def execute(self,context):
        a=current(context)
        if not a:return {'CANCELLED'}
        s=a.poster_scatter
        s.lift_enabled=True;s.curl_bottom=True;s.curl_side=False;s.curl_corner=False;s.roll_enabled=False
        s.bend_start=.2;s.curl_shape=2.6;s.bottom_lift_percent=24.;s.lift_random=True;s.lift_min_percent=5.
        s.bend_faces=max(s.bend_faces,8)
        try:rebuild(a)
        except Exception as exc:self.report({'WARNING'},_T(str(exc)))
        self.report({'INFO'},_T('Sticky note lift: glue strip 20 %, lift 5-24 %.'));return {'FINISHED'}


class PS_OT_pin_reset(bpy.types.Operator):
    bl_idname='poster_scatter.pin_reset';bl_label=_T('Reset Tape & Objects');bl_options={'UNDO'}
    bl_description=_T('Put every Tape & Objects setting back to default. The chosen collection / object is kept')
    def execute(self,context):
        a=current(context)
        if not a:return {'CANCELLED'}
        s=a.poster_scatter
        for k in PIN_KEYS:s.property_unset(k)
        try:rebuild(a)
        except Exception as exc:self.report({'WARNING'},_T(str(exc)))
        self.report({'INFO'},_T('Tape & Objects settings were reset.'));return {'FINISHED'}


class PS_OT_reset(bpy.types.Operator):
    bl_idname='poster_scatter.reset';bl_label=_T('Reset Settings');bl_options={'UNDO'}
    bl_description=_T('Back to default settings (rotation, lift, overlap and reuse off, count linked). Collection, painting, pinned posters and the rail are kept')
    def execute(self,context):
        a=current(context)
        if not a:return {'CANCELLED'}
        s=a.poster_scatter
        for k in RESET_KEYS:s.property_unset(k)
        if a.get('ps_rail_auto'):s.layout='RAIL';s.repeat=True   # A scatter made from a rail stays a rail
        s.repeat_ranges.clear();ensure_repeat_ranges(s);s.count_auto=True;apply_auto_count(s)
        try:rebuild(a)
        except Exception as exc:self.report({'WARNING'},_T(str(exc)))
        self.report({'INFO'},_T('Scatter settings were reset to defaults.'));return {'FINISHED'}


def _inside(poly,x,y):
    sg=0
    for (ax,ay),(bx,by) in zip(poly,poly[1:]+poly[:1]):
        c=(bx-ax)*(y-ay)-(by-ay)*(x-ax)
        if abs(c)<1e-12:continue
        if sg==0:sg=1 if c>0 else -1
        elif (c>0)!=(sg>0):return False
    return True


def _area_flat_hit(area,region,rv3d,mouse):
    """Mouse ray -> (flat x, y, world distance) on a scatter area, or None."""
    from bpy_extras import view3d_utils
    o=view3d_utils.region_2d_to_origin_3d(region,rv3d,mouse);d=view3d_utils.region_2d_to_vector_3d(region,rv3d,mouse)
    inv=area.matrix_world.inverted();lo=inv@o;ld=(inv.to_3x3()@d).normalized()
    mesh=area.data;mesh.calc_loop_triangles()
    if area_flat(mesh) is not None:   # Curved: hit the real surface, convert to unfolded coordinates
        smap=SurfaceMap(mesh);loc,_,idx,_=smap.surface.ray_cast(lo,ld)
        if idx is None:return None
        f=smap.to_flat(idx,loc);return f.x,f.y,(area.matrix_world@loc-o).length
    tree=BVHTree.FromPolygons([v.co for v in mesh.vertices],[tuple(t.vertices) for t in mesh.loop_triangles],all_triangles=True)
    loc,_,idx,_=tree.ray_cast(lo,ld)
    if idx is None:   # Papers sit a little in front of the wall: fall back to the wall plane
        if abs(ld.z)<1e-9:return None
        t=-lo.z/ld.z
        if t<0:return None
        loc=lo+ld*t
    return loc.x,loc.y,(area.matrix_world@loc-o).length


def grab_poster(context,area,j):
    """Turn placed poster j into a manual placement (other posters keep their spots). Returns the manual index."""
    s=area.poster_scatter;info=PICKS.get(area.as_pointer())
    kind,val=info['kinds'][j]
    if kind=='M':return val
    x,y,idx,angle,k=val;name=info['names'][idx];poster=bpy.data.objects.get(name)
    if poster is None:return -1
    autos=[v for kd,v in info['kinds'] if kd=='A']
    if val in autos:autos.remove(val)
    _SUPPRESS[0]=True
    try:
        s['ps_frozen']=[float(c) for r in autos for c in r];s['ps_frozen_key']=info['key']
        item=s.manual.add();item.poster=poster;item.x,item.y,item.angle,item.scale=x,y,angle,k;item.no_lift=False
    finally:_SUPPRESS[0]=False
    rebuild(area);SIGNATURES[area.as_pointer()]=signature(area)
    return len(s.manual)-1


class PS_OT_grab(bpy.types.Operator):
    bl_idname='poster_scatter.grab';bl_label=_T('Click Poster to Grab');bl_options={'UNDO'}
    bl_description=_T('Click any poster on the wall to pick it up: it becomes a manual placement you can move (mouse), rotate (R) and scale (S). The other posters stay where they are')
    def invoke(self,context,event):
        if context.area is None or context.area.type!='VIEW_3D':self.report({'WARNING'},_T('Use it from the 3D View.'));return {'CANCELLED'}
        if PLACERS:self.report({'WARNING'},_T('Finish the current placement first.'));return {'CANCELLED'}
        self.area=context.area;self.region=next(r for r in self.area.regions if r.type=='WINDOW');self.rv3d=self.area.spaces.active.region_3d
        self.area.header_text_set('Click a poster to grab it · Esc cancel');context.window.cursor_modal_set('EYEDROPPER')
        context.window_manager.modal_handler_add(self);return {'RUNNING_MODAL'}
    def end(self,context):
        self.area.header_text_set(None);context.window.cursor_modal_restore()
    def pick(self,context,event):
        mouse=(event.mouse_x-self.region.x,event.mouse_y-self.region.y);best=None
        for area in context.scene.objects:
            s=area.poster_scatter
            # The area object itself is usually hidden (Show Scatter Area Bounds off); what matters is that its posters are visible
            if not s.enabled or not s.output or area.as_pointer() not in PICKS or not s.output.visible_get():continue
            hit=_area_flat_hit(area,self.region,self.rv3d,mouse)
            if hit is None:continue
            x,y,dist=hit;info=PICKS[area.as_pointer()]
            top=None
            for j,(poly,h) in enumerate(info['picks']):
                if _inside(poly,x,y) and (top is None or h>=top[1]):top=(j,h)
            if top and (best is None or dist<best[2]):best=(area,top[0],dist)
        return best
    def modal(self,context,event):
        t,v=event.type,event.value
        if t in {'ESC','RIGHTMOUSE'} and v=='PRESS':self.end(context);return {'CANCELLED'}
        if t=='LEFTMOUSE' and v=='PRESS':
            if event.mouse_x<self.region.x or event.mouse_y<self.region.y or event.mouse_x>self.region.x+self.region.width or event.mouse_y>self.region.y+self.region.height:
                return {'PASS_THROUGH'}
            got=self.pick(context,event)
            if not got:self.report({'INFO'},_T('No poster there. Click a poster, or Esc.'));return {'RUNNING_MODAL'}
            area,j,_=got;self.end(context)
            try:n=grab_poster(context,area,j)
            except Exception as exc:self.report({'ERROR'},_T(str(exc)));return {'CANCELLED'}
            if n<0:self.report({'ERROR'},_T('Could not find that poster source.'));return {'CANCELLED'}
            bpy.ops.poster_scatter.place('INVOKE_DEFAULT',index=n,area_name=area.name)
            return {'FINISHED'}
        if t in {'MIDDLEMOUSE','WHEELUPMOUSE','WHEELDOWNMOUSE','TRACKPADPAN','TRACKPADZOOM','MOUSEMOVE'}:return {'PASS_THROUGH'}
        return {'RUNNING_MODAL'}


class PS_OT_unfreeze(bpy.types.Operator):
    bl_idname='poster_scatter.unfreeze';bl_label=_T('Re-spread Other Posters');bl_options={'UNDO'}
    bl_description=_T('Let the automatic posters be laid out again around your manual posters (undo the "keep where they are" from grabbing)')
    def execute(self,context):
        a=current(context)
        if not a:return {'CANCELLED'}
        s=a.poster_scatter
        for key in ('ps_frozen_key','ps_frozen'):
            if key in s:del s[key]
        rebuild(a);SIGNATURES[a.as_pointer()]=signature(a);return {'FINISHED'}


class PS_OT_remove_manual(bpy.types.Operator):
    bl_idname='poster_scatter.remove_manual';bl_label=_T('Remove Manual Placement');bl_options={'UNDO'}
    bl_description=_T('Removes a manually placed poster')
    index:IntProperty(default=-1,options={'HIDDEN','SKIP_SAVE'})
    def execute(self,context):
        a=current(context)
        if not a or not a.poster_scatter.manual:return {'CANCELLED'}
        m=a.poster_scatter.manual;i=self.index if 0<=self.index<len(m) else len(m)-1
        m.remove(i);rebuild(a);SIGNATURES[a.as_pointer()]=signature(a);return {'FINISHED'}

def paint_view(context, colors=True):
    areas=[context.area] if context.area and context.area.type=='VIEW_3D' else [ar for ar in context.screen.areas if ar.type=='VIEW_3D']
    for ar in areas:
        space=ar.spaces.active
        space.shading.type='SOLID' if colors else 'MATERIAL'
        if colors:
            space.shading.color_type='VERTEX'
            space.overlay.show_overlays=True
            space.overlay.vertex_paint_mode_opacity=1.0
        ar.tag_redraw()

def mark_face_area(area,target,from_faces):
    """Remember that an area was made from only some faces of target: hiding target would hide the rest too."""
    if from_faces:area['ps_from_faces']=target.name
    elif 'ps_from_faces' in area.keys():del area['ps_from_faces']


def source_hide_changed(s,context):
    o=s.source_surface
    if getattr(s.id_data,'get',None) and s.id_data.get('ps_from_faces'):return   # part of a bigger object: never hide the whole object
    if o is not None and getattr(o,'poster_scatter',None) is not None and not o.poster_scatter.enabled:
        o.hide_render=s.hide_source


PAINT_STATE={}


def paint_begin(context,area):
    """Remember the view state before painting (restored when done)."""
    if PAINT_STATE.get('area')==area.name:return
    PAINT_STATE.clear()
    views=[]
    for w in context.window_manager.windows:
        for ar in w.screen.areas:
            if ar.type=='VIEW_3D':sh=ar.spaces.active.shading;views.append((ar.as_pointer(),sh.type,sh.color_type))
    PAINT_STATE.update(area=area.name,hidden=area.hide_get(),display=area.display_type,views=views,front=area.show_in_front,
                       mode=context.object.mode if context.object else 'OBJECT',
                       active=context.view_layer.objects.active.name if context.view_layer.objects.active else '',
                       selected=[o.name for o in context.selected_objects])
    if not bpy.app.timers.is_registered(paint_watch):bpy.app.timers.register(paint_watch,first_interval=.5)


def paint_end():
    """When painting ends, hide the paint surface again and restore view, selection and mode."""
    st=dict(PAINT_STATE);PAINT_STATE.clear()
    a=bpy.data.objects.get(st.get('area',''))
    if a is None:return
    ctx=bpy.context;vl=ctx.view_layer
    try:
        if a.mode!='OBJECT' and vl.objects.active==a:bpy.ops.object.mode_set(mode='OBJECT')
    except RuntimeError:pass
    a.display_type='BOUNDS' if st.get('display','BOUNDS')=='TEXTURED' else st.get('display','BOUNDS')
    a.show_in_front=bool(st.get('front',False))
    try:a.hide_set(st.get('hidden',False))
    except RuntimeError:pass
    keep={p:(t,c) for p,t,c in st.get('views',[])}
    for w in ctx.window_manager.windows:
        for ar in w.screen.areas:
            if ar.as_pointer() in keep:
                t,c=keep[ar.as_pointer()];sh=ar.spaces.active.shading;sh.type=t
                try:sh.color_type=c
                except TypeError:pass
                ar.tag_redraw()
    for o in vl.objects:
        if o.select_get():o.select_set(False)
    for n in st.get('selected',[]):
        o=vl.objects.get(n)
        if o and o.visible_get():o.select_set(True)
    act=vl.objects.get(st.get('active',''))
    if act:
        vl.objects.active=act
        mode=st.get('mode','OBJECT')
        if mode not in ('OBJECT','VERTEX_PAINT') and act.type=='MESH':
            try:bpy.ops.object.mode_set(mode=mode)
            except RuntimeError:pass


def paint_watch():
    a=bpy.data.objects.get(PAINT_STATE.get('area','')) if PAINT_STATE else None
    if a is None:PAINT_STATE.clear();return None
    if a.mode=='VERTEX_PAINT':return .3
    paint_end();return None


class PS_OT_paint_end(bpy.types.Operator):
    bl_idname='poster_scatter.paint_end';bl_label=_T('Finish Painting');bl_description=_T('Finish painting and return to the view and mode from before')
    def execute(self,context):
        a=bpy.data.objects.get(PAINT_STATE.get('area','')) if PAINT_STATE else current(context)
        if a and a.mode=='VERTEX_PAINT' and context.view_layer.objects.active==a:bpy.ops.object.mode_set(mode='OBJECT')
        if PAINT_STATE:paint_end()
        return {'FINISHED'}


class PS_OT_view(bpy.types.Operator):
    bl_idname='poster_scatter.view';bl_label=_T('Toggle Preview')
    colors:BoolProperty(default=True)
    def execute(self,context):
        paint_view(context,self.colors)
        a=current(context)
        if a:a.display_type='TEXTURED' if self.colors else 'BOUNDS';a.show_in_front=self.colors   # colors: paint over the placed posters · posters: back on top
        return {'FINISHED'}

class PS_OT_paint(bpy.types.Operator):
    bl_idname='poster_scatter.paint';bl_label=_T('Paint Area')
    kind:EnumProperty(items=_T_items([(x,x,'') for x in ['Add','Erase','Seed','Reset Seed']]))
    def execute(self,context):
        a=current(context)
        if not a:return {'CANCELLED'}
        paint_begin(context,a)
        if context.object and context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
        for o in context.selected_objects:o.select_set(False)
        a.hide_set(False);a.display_type='TEXTURED';a.select_set(True);context.view_layer.objects.active=a
        a.show_in_front=True   # the paint shows over the placed posters (they covered it); restored when painting ends
        attr=MASK if self.kind in {'Add','Erase'} else SEED
        color={'Add':(1,1,1),'Erase':(0,0,0),'Seed':(1,1,1),'Reset Seed':(0,0,0)}[self.kind]
        a.data.color_attributes.active_color=a.data.color_attributes[attr]
        bpy.ops.object.mode_set(mode='VERTEX_PAINT')
        try:bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS',relative_asset_identifier='brushes/essentials_brushes-mesh_vertex.blend/Brush/Paint Hard')
        except RuntimeError:pass
        ups=context.scene.tool_settings.vertex_paint.unified_paint_settings;ups.use_unified_color=True;ups.color=color
        paint_view(context)
        return {'FINISHED'}

class PS_OT_fill(bpy.types.Operator):
    bl_idname='poster_scatter.fill';bl_label=_T('Fill Current Paint');bl_options={'UNDO'}
    def execute(self,context):
        a=current(context)
        if not a:return {'CANCELLED'}
        attr=a.data.color_attributes.active_color
        color=tuple(context.scene.tool_settings.vertex_paint.unified_paint_settings.color)+(1,)
        attr.data.foreach_set('color',np.tile(color,len(attr.data)));a.data.update();return {'FINISHED'}

class PS_OT_invert(bpy.types.Operator):
    bl_idname='poster_scatter.invert';bl_label=_T('Invert Paint');bl_options={'UNDO'}
    bl_description=_T('Inverts the visible paint: painted <-> unpainted (for the placeable mask, where posters go and where they do not swap)')
    def execute(self,context):
        a=current(context)
        if not a:return {'CANCELLED'}
        attr=a.data.color_attributes.active_color or a.data.color_attributes.get(MASK)
        if attr is None:return {'CANCELLED'}
        n=len(attr.data);buf=np.empty(n*4,np.float32);attr.data.foreach_get('color',buf);buf=buf.reshape(n,4)
        buf[:,:3]=1-np.clip(buf[:,:3],0,1);attr.data.foreach_set('color',buf.ravel())
        a.data.update()
        for ar in context.screen.areas:ar.tag_redraw()
        return {'FINISHED'}


def ps_area_invisible(o):
    """Rendered viewports (Cycles/EEVEE) ignore hide_render and draw the area as a white surface -> hide it from all rays."""
    for k in ('visible_camera','visible_diffuse','visible_glossy','visible_transmission','visible_volume_scatter','visible_shadow'):
        if hasattr(o,k) and getattr(o,k):setattr(o,k,False)


def _ps_fix_areas_now():
    for sc in list(bpy.data.scenes):
        try:
            for o in ps_area_objects(sc):ps_area_invisible(o)
            ps_apply_sources(sc)
        except Exception:pass
    return None


@bpy.app.handlers.persistent
def _ps_fix_areas(*_):
    # Never change data inside the undo / redo / load callback itself: Blender is still swapping the file state there,
    # and touching objects then crashed it (Ctrl+Z right after adding Tape & Objects, 2026-10-13). Run a moment later.
    if not bpy.app.timers.is_registered(_ps_fix_areas_now):bpy.app.timers.register(_ps_fix_areas_now,first_interval=.05)


def ps_area_objects(scene):
    """Scatter area objects (non-rendering bounds boxes). Results are their children and stay visible."""
    return [o for o in scene.objects if o.get('ps_owned') and o.type=='MESH' and o.hide_render and o.display_type in ('BOUNDS','WIRE')]


def ps_show_areas_changed(self,context):
    for o in ps_area_objects(self):
        try:o.hide_set(not self.ps_show_areas)
        except RuntimeError:pass


def ps_source_collections(scene):
    """Poster collections used by scatter areas in this scene, plus the one picked for the next area."""
    cols=set()
    for o in scene.objects:
        s=getattr(o,'poster_scatter',None)
        if s and s.output and s.collection:cols.add(s.collection)
    return cols


def ps_inside(col,sources):
    """True if col is a source collection or nested inside one."""
    for src in sources:
        if col==src or col.name in {c.name for c in src.children_recursive}:return True
    return False


def ps_home_collection(context,target):
    """Where new area/result objects go: never inside a poster source collection (hiding the sources would hide them too)."""
    srcs=ps_source_collections(context.scene)
    pick=context.scene.poster_scatter_setup.collection
    if pick:srcs.add(pick)
    for col in [context.collection]+list(target.users_collection)+[context.scene.collection]:
        if col and not ps_inside(col,srcs) and (col==context.scene.collection or col.name in {c.name for c in context.scene.collection.children_recursive}):return col
    return context.scene.collection


def ps_find_layers(lc,col,out=None):
    """Every layer collection of col (a collection linked in several places has several)."""
    out=[] if out is None else out
    if lc.collection==col:out.append(lc)
    for c in lc.children:ps_find_layers(c,col,out)
    return out


def ps_find_layer(lc,col):
    if lc.collection==col:return lc
    for c in lc.children:
        r=ps_find_layer(c,col)
        if r:return r
    return None


def ps_apply_sources(scene):
    """Show or hide the source poster gallery of collections already used by a scatter area. Placed posters stay visible."""
    if not getattr(scene,'ps_show_areas',False):   # After placement, hide the area bounds box (wire box around poles/walls)
        painting=PAINT_STATE.get('area') if PAINT_STATE else None
        for o in ps_area_objects(scene):
            if o.name==painting:continue
            try:
                if not o.hide_get():o.hide_set(True)
            except RuntimeError:pass
    show=getattr(scene,'ps_show_sources',False);srcs=ps_source_collections(scene)
    if not srcs:return
    for o in list(scene.objects):   # areas/results made by older versions may sit inside a source collection
        if not o.get('ps_owned'):continue
        bad=[c for c in o.users_collection if ps_inside(c,srcs)]
        if not bad:continue
        area=o.parent if o.parent and o.parent.get('ps_owned') else o
        wall=getattr(area.poster_scatter,'source_surface',None)
        home=next((c for c in (list(wall.users_collection) if wall else []) if not ps_inside(c,srcs)),scene.collection)
        if home not in o.users_collection:home.objects.link(o)
        for c in bad:c.objects.unlink(o)
    targets=set(srcs)
    for col in srcs:targets.update(col.children_recursive)   # e.g. 'Group · Wall' only links the batches' group collections
    for col in targets:
        if col.hide_render==show:col.hide_render=not show
        for vl in scene.view_layers:
            for lc in ps_find_layers(vl.layer_collection,col):
                if lc.hide_viewport==show:lc.hide_viewport=not show


def ps_show_sources_changed(self,context):
    ps_apply_sources(self)


class PS_OT_rail_edges(bpy.types.Operator):
    bl_idname='poster_scatter.rail_edges';bl_label=_T('Use Selected Edges');bl_options={'UNDO'}
    bl_description=_T('Use the edges selected on the rail mesh (in Edit Mode) as the rail. With Clear, every edge is used again')
    clear:BoolProperty(default=False,options={'SKIP_SAVE'})
    def execute(self,context):
        a=current(context);o=a.poster_scatter.rail_object if a else None
        if o is None or o.type!='MESH':self.report({'ERROR'},_T('Pick a mesh as the rail first.'));return {'CANCELLED'}
        me=o.data
        if o.mode=='EDIT':
            bm=bmesh.from_edit_mesh(me);lay=bm.edges.layers.bool.get(RAIL) or bm.edges.layers.bool.new(RAIL);n=0
            for e in bm.edges:
                v=False if self.clear else bool(e.select);e[lay]=v;n+=v
            bmesh.update_edit_mesh(me)
        else:
            sel=np.zeros(len(me.edges),bool);me.edges.foreach_get('select',sel)
            if self.clear:sel[:]=False
            att=me.attributes.get(RAIL)
            if att is not None and (att.domain!='EDGE' or att.data_type!='BOOLEAN'):me.attributes.remove(att);att=None
            if att is None:att=me.attributes.new(RAIL,'BOOLEAN','EDGE')
            att.data.foreach_set('value',sel);me.update();n=int(sel.sum())
        if self.clear:self.report({'INFO'},_T('Rail uses all edges'))
        elif n==0:self.report({'WARNING'},_T('No edges were selected, so all edges are used'))
        else:self.report({'INFO'},_T('Rail uses %d edge%s'%(n,'' if n==1 else 's')))
        return {'FINISHED'}


def rail_front(context,o):
    """Which way the papers face: the faces next to the rail edges (a shelf's front), else toward the viewer."""
    if o.type=='MESH' and len(o.data.polygons):
        me=o.data;att=me.attributes.get(RAIL);keys=None
        if att is not None and att.domain=='EDGE' and att.data_type=='BOOLEAN':
            m=np.zeros(len(att.data),bool);att.data.foreach_get('value',m)
            keys={tuple(sorted(me.edges[i].vertices)) for i in np.nonzero(m)[0]}
        n=Vector()
        for p in me.polygons:
            if keys is None or any(tuple(sorted(k)) in keys for k in p.edge_keys):n+=p.normal
        n=o.matrix_world.to_3x3().inverted().transposed()@n;n.z=0
        if n.length>1e-6:return n.normalized()
    rv=getattr(getattr(context,'space_data',None),'region_3d',None)
    if rv is not None:
        f=-(rv.view_rotation@Vector((0,0,-1)));f.z=0
        if f.length>1e-6:return f.normalized()
    return Vector((0,-1,0))


def rail_ribbon(o,front,height,above):
    """An invisible curtain hanging from the rail: the surface the papers are laid out on."""
    g=rail_geometry(o)
    if g is None:raise ValueError('The rail has no edges to hang from.')
    V,E=g;verts=[];faces=[]
    for path,closed in chain_edges(E):
        P=V[path];n=len(P)
        if n<2:continue
        base=len(verts)
        verts+=[(x,y,z+above) for x,y,z in P]+[(x,y,z-height) for x,y,z in P]
        quads=[(base+i,base+(i+1)%n,base+n+(i+1)%n,base+n+i) for i in range(n if closed else n-1)]
        Pv=[Vector(v) for v in verts]
        def qn(q):
            a_,b_,c_=Pv[q[0]],Pv[q[1]],Pv[q[2]];return (b_-a_).cross(c_-a_)
        quads=[q for q in quads if qn(q).length>1e-10]   # Vertical rail pieces cannot carry a hanging paper
        if not quads:continue
        if closed:   # Loops (around a pole) face outward
            cen=Vector(tuple(P.mean(0)));score=sum(qn(q).dot((Pv[q[0]]+Pv[q[1]])*.5-cen) for q in quads)
        else:score=sum(qn(q).dot(front) for q in quads)
        if score<0:quads=[tuple(reversed(q)) for q in quads]
        faces+=quads
    if not faces:raise ValueError('The rail is vertical or too short to hang papers from.')
    return verts,faces


def merged_rail_line(context,objs):
    """Several selected strings -> one line object (mesh edges only, not rendered) that holds all of them,
    highest string first so it fills first. Returns the new object."""
    parts=[]
    for o in objs:
        g=rail_geometry(o)
        if g is not None and len(g[1]):parts.append((float(g[0][:,2].max()),o,g))
    if len(parts)<2:raise ValueError('Select at least two strings (curves or lines) to hang along all of them.')
    parts.sort(key=lambda t:-t[0])
    verts=[];edges=[]
    for _,o,(V,E) in parts:
        base=len(verts);verts+=[tuple(map(float,v)) for v in V];edges+=[(int(a)+base,int(b)+base) for a,b in E]
    names=' + '.join(o.name for _,o,_ in parts)
    me=bpy.data.meshes.new('Rail Line · '+names);me.from_pydata(verts,edges,[]);me.update()
    line=bpy.data.objects.new('Rail Line · '+names,me);line.hide_render=True;line.display_type='WIRE'
    act=context.object or parts[0][1]
    home=act.users_collection[0] if act.users_collection else context.scene.collection;home.objects.link(line)
    return line


class PS_OT_create_rail(bpy.types.Operator):
    bl_idname='poster_scatter.create_rail';bl_label=_T('Scatter Along Rail');bl_options={'UNDO'}
    bl_description=_T('Hang posters along the selected curve, or the selected edges in Edit Mode. Select several strings to hang along all of them (they are joined into one line). No wall area is needed: an invisible one is made under the rail and follows it')
    def execute(self,context):
        ob=context.object
        try:
            many=[o for o in context.selected_objects if o.type in {'CURVE','MESH'}]
            if len(many)>1 and (ob is None or ob.mode=='OBJECT'):   # Several strings picked: hang along all of them as one rail
                ob=merged_rail_line(context,many)
            if ob is None or ob.type not in {'CURVE','MESH'}:raise ValueError('Select a curve, or edges of a mesh.')
            if ob.type=='MESH' and ob.mode=='EDIT':   # Remember the selected edges as the rail
                bm=bmesh.from_edit_mesh(ob.data);lay=bm.edges.layers.bool.get(RAIL) or bm.edges.layers.bool.new(RAIL);n=0
                for e in bm.edges:
                    v=bool(e.select);e[lay]=v;n+=v
                bmesh.update_edit_mesh(ob.data)
                if not n:raise ValueError('Select the edges to hang the posters from.')
            if ob.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
            col=context.scene.poster_scatter_setup.collection
            tall=max([max(o.dimensions) for o in (col.all_objects if col else []) if o.type=='MESH']+[.3])
            front=rail_front(context,ob)
            verts,faces=rail_ribbon(ob,front,tall*1.6+.05,.05)
            me=bpy.data.meshes.new('_ps_rail_curtain');me.from_pydata(verts,[],faces);me.update()
            tmp=bpy.data.objects.new('Rail · '+ob.name,me)
            home=ob.users_collection[0] if ob.users_collection else context.scene.collection;home.objects.link(tmp)
            try:area=create_area(context,tmp,False,build=False)
            finally:bpy.data.objects.remove(tmp,do_unlink=True);bpy.data.meshes.remove(me)
            area.name='Poster Rail Area · '+ob.name
            s=area.poster_scatter;s.hide_source=False;s.layout='RAIL';s.rail_object=ob;s.repeat=True;area['ps_rail_auto']=True
            if s.output:s.output.name='Poster Rail Result · '+ob.name
            mw=area.matrix_world.copy();area.parent=ob;area.matrix_parent_inverse=ob.matrix_world.inverted();area.matrix_world=mw   # Follows the rail
            if s.collection:
                try:refresh_sources(area);rebuild(area)
                except ValueError as exc:s.status=str(exc)
            for o in context.selected_objects:o.select_set(False)
            area.select_set(True);context.view_layer.objects.active=area
            n=len(s.output.data.vertices) if s.output else 0
            if not s.collection:self.report({'WARNING'},_T('Rail made. Pick a poster collection in the panel to hang posters.'))
            else:self.report({'INFO'},_T('Hung %d poster%s along %s.'%(n,'' if n==1 else 's',ob.name)))
            return {'FINISHED'}
        except Exception as exc:self.report({'ERROR'},_T(str(exc)));return {'CANCELLED'}


UI_SECTIONS=('posters','layers','layout','manual','repeat','pins','rotation','overlap','lift','paint','finish','help')
LAYOUT_HINTS={'RANDOM':'Natural spread at random spots','PACK':'Big ones first, small ones fill gaps',
              'GRID':'Tight overlapping board (sticky notes)','RAIL':'Hang along a curve or edges'}


class PS_UIState(bpy.types.PropertyGroup):
    """Which panel sections are open. Kept per scene so Collapse All can switch them together."""
    posters:BoolProperty(name=_T('Posters'),default=True)
    layout:BoolProperty(name=_T('Layout'),default=True)
    rotation:BoolProperty(name=_T('Rotation'),default=True)
    lift:BoolProperty(name=_T('Paper Lift'),default=False)
    overlap:BoolProperty(name=_T('Overlap'),default=False)
    layers:BoolProperty(name=_T('Layers'),default=True)
    pins:BoolProperty(name=_T('Tape & Objects'),default=False)
    repeat:BoolProperty(name=_T('Reuse'),default=False)
    paint:BoolProperty(name=_T('Paint'),default=False)
    manual:BoolProperty(name=_T('Place'),default=False)
    finish:BoolProperty(name=_T('Finish'),default=True)
    help:BoolProperty(name=_T('Guide'),default=False)
    setup_more:BoolProperty(name=_T('More Options'),default=False)


class PS_OT_ui_fold(bpy.types.Operator):
    bl_idname='poster_scatter.ui_fold';bl_label=_T('Collapse or Expand All')
    bl_description=_T('Fold or unfold every section of the Poster Scatter panel at once')
    open:BoolProperty(default=False,options={'SKIP_SAVE'})
    def execute(self,context):
        ui=context.scene.ps_ui
        for k in UI_SECTIONS:setattr(ui,k,self.open)
        for ar in context.screen.areas:
            if ar.type=='VIEW_3D':ar.tag_redraw()
        return {'FINISHED'}


def ps_show_results_changed(self,context):
    """Show or hide the placed posters of every scatter in the scene (viewport only)."""
    for o in self.objects:
        s=getattr(o,'poster_scatter',None)
        if s is not None and s.enabled and s.output:s.output.hide_viewport=not self.ps_show_results
        if s is not None and s.enabled and s.pin_output:s.pin_output.hide_viewport=not self.ps_show_results


def ui_section(layout,ui,key,title,icon,toggle=None):
    """A foldable section with a ∨ header. toggle=(data, prop) adds an on/off checkbox to the header."""
    header,body=layout.panel_prop(ui,key)
    if toggle:header.prop(toggle[0],toggle[1],text=_T(''))
    header.label(text=_T(title),icon=icon)
    return body


def selection_kind(context):
    """What the current selection would scatter onto: WALL, FACES, CURVE, EDGES, LINE or None."""
    ob=context.object
    if ob is None:return None,None
    if ob.type=='CURVE':return 'CURVE',ob
    if ob.type!='MESH':return None,ob
    if ob.mode=='EDIT':return ('FACES' if context.tool_settings.mesh_select_mode[2] else 'EDGES'),ob
    return ('WALL' if len(ob.data.polygons) else 'LINE'),ob


class PS_PT_panel(bpy.types.Panel):
    bl_label=_T('Poster Pin');bl_idname='PS_PT_panel';bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='Poster Pin'

    def draw(self,context):
        l=self.layout;sc=context.scene;ui=sc.ps_ui;area=current(context)
        self.draw_top(l,sc,ui,area)
        if area is None:self.draw_setup(context,l,sc,ui)
        else:self.draw_area(context,l,sc,ui,area)

    # Visibility toggles for everything, plus fold/unfold all sections
    def draw_top(self,l,sc,ui,area):
        row=l.row(align=True)
        row.prop(sc,'ps_show_results',text=_T('Posters'),icon='HIDE_OFF' if sc.ps_show_results else 'HIDE_ON',toggle=True)
        row.prop(sc,'ps_show_sources',text=_T('Sources'),icon='HIDE_OFF' if sc.ps_show_sources else 'HIDE_ON',toggle=True)
        row.prop(sc,'ps_show_areas',text=_T('Areas'),icon='HIDE_OFF' if sc.ps_show_areas else 'HIDE_ON',toggle=True)
        if area is not None:
            opened=any(getattr(ui,k) for k in UI_SECTIONS)
            row.separator()
            row.operator('poster_scatter.ui_fold',text=_T(''),icon='TRIA_UP' if opened else 'TRIA_DOWN').open=not opened

    # No scatter selected: a three-step start
    def draw_setup(self,context,l,sc,ui):
        s=sc.poster_scatter_setup;kind,ob=selection_kind(context)
        box=l.box();col=box.column()
        col.label(text=_T('Get Started'),icon='INFO')
        col.label(text=_T('1. Pick your poster collection'),icon='CHECKBOX_HLT' if s.collection else 'CHECKBOX_DEHLT')
        col.prop(s,'collection',text=_T(''))
        if s.collection:
            n=len(sources(s.collection))
            r=col.row();r.alert=not n;r.label(text=_T(('%d poster object%s inside'%(n,'' if n==1 else 's')) if n else 'No mesh posters in it'),icon='DOT')
        else:col.label(text=_T('Flat poster planes, e.g. from Poster Atlas'),icon='DOT')
        col.separator()
        col.label(text=_T('2. Select where they go'),icon='CHECKBOX_HLT' if kind else 'CHECKBOX_DEHLT')
        if kind is None:col.label(text=_T('A wall, floor, curve or edges'),icon='DOT')
        elif kind=='WALL':col.label(text=_T('All faces of '+ob.name),icon='OBJECT_DATA')
        elif kind=='FACES':col.label(text=_T('Selected faces of '+ob.name),icon='FACESEL')
        elif kind=='CURVE':col.label(text=_T('Hang along '+ob.name),icon='CURVE_DATA')
        elif kind=='EDGES':col.label(text=_T('Hang along the selected edges'),icon='EDGESEL')
        else:col.label(text=_T('Hang along the edges of '+ob.name),icon='EDGESEL')
        col.separator()
        col.label(text=_T('3. Press the button'),icon='CHECKBOX_DEHLT')
        row=box.row();row.scale_y=1.6;row.enabled=kind is not None
        if kind in ('CURVE','EDGES','LINE'):
            row.operator('poster_scatter.create_rail',text=_T('Scatter Along Curve' if kind=='CURVE' else 'Scatter Along Edges'),icon='CURVE_PATH')
        else:row.operator('poster_scatter.create',text=_T('Scatter on Selected Faces' if kind=='FACES' else 'Scatter on This Wall'),icon='PARTICLES')
        if kind is not None and not s.collection:
            r=box.row();r.alert=True;r.label(text=_T('Pick a collection first'),icon='ERROR')
        if kind=='FACES':box.label(text=_T('Edge select mode hangs along edges'),icon='INFO')
        body=ui_section(l,ui,'setup_more','More Options','PREFERENCES')
        if body:
            body.prop(s,'paint_step')
            body.prop(s,'hide_source',text=_T('Hide Picked Plane in Render'))

    def draw_area(self,context,l,sc,ui,a):
        s=a.poster_scatter;rail_auto=bool(a.get('ps_rail_auto'))
        # Overview: what this is, how the last update went, quick actions
        box=l.box();col=box.column(align=True)
        what=('Rail · '+s.rail_object.name) if rail_auto and s.rail_object else ('Curved surface' if s.curved else 'Wall / floor')
        col.label(text=_T(what),icon='CURVE_PATH' if rail_auto else ('MOD_CURVE' if s.curved else 'MESH_PLANE'))
        err=s.status.startswith('Placement error')
        r=col.row();r.alert=err or not s.source_count
        r.label(text=_T(s.status if s.status else 'Not placed yet'),icon='ERROR' if (err or not s.source_count) else 'CHECKMARK')
        row=box.row(align=True)
        row.operator('poster_scatter.update',text=_T('Update'),icon='FILE_REFRESH')
        row.prop(s,'live',text=_T('Live'),toggle=True,icon='PLAY' if s.live else 'PAUSE')
        row.operator('poster_scatter.reset',text=_T('Reset'),icon='LOOP_BACK')
        if err and not s.live:box.label(text=_T('Live paused by the error'),icon='INFO')
        if not s.collection:
            r=box.row();r.alert=True;r.label(text=_T('Pick a poster collection below'),icon='ERROR')
        self.draw_posters(l,ui,s,a,rail_auto)
        self.draw_layers(l,ui,s,a)
        self.draw_layout(l,ui,s,a)
        self.draw_manual(l,ui,s)
        self.draw_repeat(l,ui,s)
        self.draw_pins(l,ui,s)
        self.draw_rotation(l,ui,s)
        self.draw_overlap(l,ui,s,a)
        self.draw_lift(l,ui,s)
        self.draw_paint(l,ui,s,a)
        self.draw_finish(l,ui,s)
        self.draw_help(l,ui)

    def draw_posters(self,l,ui,s,a,rail_auto):
        body=ui_section(l,ui,'posters','Posters','IMAGE_DATA')
        if not body:return
        body.prop(s,'collection',text=_T(''))
        row=body.row(align=True)
        r=row.row();r.alert=not s.source_count
        r.label(text=_T('%d poster%s ready'%(s.source_count,'' if s.source_count==1 else 's')),icon='CHECKMARK' if s.source_count else 'ERROR')
        row.operator('poster_scatter.update',text=_T('Reload'),icon='FILE_REFRESH').reload=True
        if s.collection and s.cached_sources and s.cached_sources!=source_signature_cached(s.collection):
            r=body.row();r.alert=True;r.label(text=_T('Collection changed · press Reload'),icon='ERROR')
        if s.get('ps_note'):body.label(text=_T(s['ps_note'][:60]),icon='INFO')
        if not rail_auto:
            row=body.row(align=True);row.prop(s,'source_surface',text=_T('Wall'))
            sub=row.row(align=True);sub.enabled=s.source_surface is not None and not a.get('ps_from_faces')
            sub.prop(s,'hide_source',text=_T(''),icon='RESTRICT_RENDER_ON' if s.hide_source else 'RESTRICT_RENDER_OFF')
            if a.get('ps_from_faces'):r_=body.row();r_.active=False;r_.label(text=_T('Made from part of %s · it stays in renders'%a['ps_from_faces']),icon='INFO')
        if s.curved and s.layout=='RAIL':body.label(text=_T('Rail: papers hang flat from the line'),icon='CURVE_PATH')
        elif s.curved:
            box=body.box();box.label(text=_T('Curved Surface'),icon='MOD_CURVE')
            box.row(align=True).prop(s,'surface_mode',expand=True)
            if s.surface_mode=='CONFORM':
                row=box.row(align=True);row.prop(s,'conform_faces',text=_T('Across'));row.prop(s,'conform_faces_v',text=_T('Down'))

    def draw_layout(self,l,ui,s,a):
        body=ui_section(l,ui,'layout','Layout','MOD_ARRAY')
        if not body:return
        body.prop(s,'layout',text=_T(''))
        body.label(text=_T(LAYOUT_HINTS.get(s.layout,'')),icon='INFO')
        if s.layout=='GRID':
            box=body.box();col=box.column(align=True)
            for k in ('grid_overlap','grid_jitter','grid_fill'):col.prop(s,k)
            box.prop(s,'grid_stagger')
            if s.count_auto and s.repeat:box.label(text=_T('Count linked + reuse: fills it all'))
        elif s.layout=='RAIL':self.draw_rail(body,s)
        elif s.layout=='PACK':
            col=body.column(align=True)
            col.label(text=_T('Count is an upper limit'))
            col.label(text=_T('Less rotation packs tighter'))
            if not s.repeat:col.label(text=_T('Reuse off: stops when all are used'))
        col=body.column(align=True)
        row=col.row(align=True);row.prop(s,'count');row.prop(s,'count_auto',text=_T(''),icon='LINKED' if s.count_auto else 'UNLINKED')
        if s.count_auto:col.label(text=_T('= %d posters%s'%(s.source_count,' × reuse' if s.repeat else '')))
        col=body.column(align=True)
        col.prop(s,'seed');col.prop(s,'scale');col.prop(s,'scale_random',text=_T('Random Scale ±'))
        if s.layout in ('RANDOM','PACK') and not s.allow_overlap:col.prop(s,'gap')
        body.prop(s,'offset')

    def draw_rail(self,body,s):
        box=body.box();box.prop(s,'rail_object')
        ro=s.rail_object
        if ro is None:
            r=box.row();r.alert=True;r.label(text=_T('Pick a curve or a mesh with edges'),icon='ERROR')
        elif ro.type=='MESH':
            att=ro.data.attributes.get(RAIL);n=0
            if att is not None and att.domain=='EDGE' and att.data_type=='BOOLEAN':
                m=np.zeros(len(att.data),bool);att.data.foreach_get('value',m);n=int(m.sum())
            row=box.row(align=True);row.operator('poster_scatter.rail_edges',icon='EDGESEL')
            op=row.operator('poster_scatter.rail_edges',text=_T(''),icon='X');op.clear=True
            box.label(text=_T(('%d marked edges'%n) if n else 'Using all edges'),icon='CHECKMARK' if n else 'INFO')
        col=box.column(align=True);col.prop(s,'rail_overlap');col.prop(s,'rail_jitter')
        col=box.column(align=True);col.prop(s,'rail_drop');col.prop(s,'rail_drop_random');col.prop(s,'rail_swing')
        box.prop(s,'rail_hang');box.prop(s,'rail_order')
        row=box.row(align=True);row.prop(s,'rail_pick',expand=True)
        if s.rail_pick=='SHUFFLE':row.prop(s,'seed',text=_T('Seed'))
        row=box.row(align=True);row.prop(s,'rail_slide')
        row.prop(s,'rail_wrap',text=_T(''),icon='LOOP_FORWARDS');row.prop(s,'rail_reverse',text=_T(''),icon='ARROW_LEFTRIGHT')
        box.prop(s,'rail_margin')
        if s.count_auto and s.repeat:box.label(text=_T('Count linked + reuse: fills the rail'))

    def draw_rotation(self,l,ui,s):
        body=ui_section(l,ui,'rotation','Rotation','ORIENTATION_GIMBAL')
        if not body:return
        row=body.row(align=True)
        for ax in 'xyz':row.prop(s,'rot_%s_on'%ax,toggle=True)
        if s.rot_x_on or s.rot_y_on or s.rot_z_on:
            col=body.column(align=True)
            for ax in 'xyz':
                if not getattr(s,'rot_%s_on'%ax):continue
                r=col.row(align=True);r.prop(s,'rot_%s_angle'%ax,text=_T(ax.upper()));r.prop(s,'rot_%s_rand'%ax,text=_T('Random ±'))
        else:body.label(text=_T('Turn on X, Y or Z (world axes)'),icon='INFO')

    def draw_lift(self,l,ui,s):
        body=ui_section(l,ui,'lift','Paper Lift & Bend','MOD_SIMPLEDEFORM',toggle=(s,'lift_enabled'))
        if not body:return
        body.operator('poster_scatter.sticky_preset',icon='FILE_BLANK')
        if not s.lift_enabled:
            body.label(text=_T('Tick the box to curl paper edges'),icon='INFO');return
        col=body.column(align=True);col.label(text=_T('How much it lifts'))
        col.prop(s,'bottom_lift_percent',text=_T(('Max ' if s.lift_random else '')+'Lift Height (%)'))
        col.prop(s,'lift_random',text=_T('Vary per Poster'))
        if s.lift_random:col.prop(s,'lift_min_percent',text=_T('Min Lift Height (%)'))
        col.prop(s,'lift_seed',text=_T('Lift Seed'))
        if s.bottom_lift_percent<0 or (s.lift_random and s.lift_min_percent<0):
            col.label(text=_T('Minus bends backward' if s.bottom_lift_percent<=0 else 'Min below 0 mixes both ways'),icon='INFO')
        col=body.column(align=True);col.label(text=_T('Which edges lift'))
        def part(key,title,desc,draw):
            sub=col.box();row=sub.row();row.prop(s,key,text=_T(title));row.label(text=_T(desc))
            inner=sub.column(align=True);inner.enabled=getattr(s,key);draw(inner)
        def bottom_ui(c):
            c.prop(s,'bend_start',text=_T('Glued Top / Bend Start'));c.prop(s,'curl_shape',text=_T('Curve (1 ramp · 2 even · 3+ tip)'))
        part('curl_bottom','Bottom','Bottom edge',bottom_ui)
        def side_ui(c):
            c.row(align=True).prop(s,'side_pair',expand=True);c.prop(s,'side_band',text=_T('Bend Width'))
        part('curl_side','Side','Left · right',side_ui)
        def corner_ui(c):
            c.row(align=True).prop(s,'corner_pair',expand=True);c.prop(s,'corner_size',text=_T('Fold Size'))
        part('curl_corner','Corner','Bottom corners',corner_ui)
        if s.curl_bottom+s.curl_side+s.curl_corner>1:col.prop(s,'curl_mix',text=_T('One Type per Poster'))
        col=body.column(align=True);col.label(text=_T('Smoothness (paper divisions)'))
        row=col.row(align=True);row.prop(s,'bend_faces',text=_T('Vertical'));row.prop(s,'bend_faces_x',text=_T('Horizontal'))
        if s.curved and s.surface_mode=='CONFORM' and s.layout!='RAIL':
            row=col.row(align=True);row.prop(s,'conform_faces',text=_T('Curve Across'));row.prop(s,'conform_faces_v',text=_T('Curve Down'))
        if s.cache and s.cache.objects:
            n=max(len(o.data.polygons) for o in s.cache.objects if o.type=='MESH')
            col.label(text=_T('Up to %d faces per paper'%n),icon='MESH_GRID')
        if (s.curl_bottom and s.bend_faces<4) or ((s.curl_side or s.curl_corner) and s.bend_faces_x<4):
            col.label(text=_T('4 or more bends smoothly'),icon='INFO')

    def draw_pins(self,l,ui,s):
        body=ui_section(l,ui,'pins','Tape & Objects','PINNED',(s,'pin_on'))
        if not body:return
        body.active=s.pin_on
        body.row().prop(s,'pin_source',expand=True)
        body.prop(s,'pin_object' if s.pin_source=='OBJECT' else 'pin_collection',text=_T(''))
        body.operator('poster_scatter.add_clip',icon='ADD')
        if not pin_source(s)[2]:
            col=body.column(align=True)
            for t in ('Pick a collection or one object.','Model them flat (XY), +Z away from the wall,','origin where they touch the paper.','Clips: origin at the grip, handle +Y up.'):col.label(text=_T(t))
            return
        body.row().prop(s,'pin_place',expand=True)
        col=body.column(align=True)
        if s.pin_place=='CORNER':
            col.row(align=True).prop(s,'pin_corners',expand=True)
            if s.pin_corners=='RANDOM':col.prop(s,'pin_corner_chance')
            col.prop(s,'pin_corner_inset')
        elif s.pin_place=='NATURAL':
            col.prop(s,'pin_tape_share');col.prop(s,'pin_corner_inset')
            kinds=sorted({pin_kind(o) for o in pin_source(s)[0].objects}) if pin_source(s)[0] else []
            if kinds:col.label(text=_T('Kinds: '+', '.join(kinds)),icon='INFO')
        elif s.pin_place!='PIVOT':col.prop(s,'pin_count')
        col.prop(s,'pin_chance')
        row=body.row(align=True);row.prop(s,'pin_skip_lifted')
        sub=row.row(align=True);sub.active=s.pin_skip_lifted;sub.prop(s,'pin_max_lift',text=_T('Gap'))
        col=body.column(align=True);row=col.row(align=True);row.prop(s,'pin_follow')
        sub=row.row(align=True);sub.active=s.pin_follow
        for k in ('pin_follow_x','pin_follow_y','pin_follow_z'):sub.prop(s,k,toggle=True)
        col.prop(s,'pin_spin')
        col=body.column(align=True);col.prop(s,'pin_scale');col.prop(s,'pin_scale_random');col.prop(s,'pin_poster_scale')
        row=body.row(align=True);row.prop(s,'pin_seed');row.prop(s,'pin_offset')
        body.operator('poster_scatter.pin_reset',icon='LOOP_BACK')

    def draw_layers(self,l,ui,s,a):
        if s.layout=='RAIL':return
        body=ui_section(l,ui,'layers','Layers','SORT_DESC')   # Right under Posters
        if not body:return
        box=body.box()
        if not s.curved:box.operator('poster_scatter.add_layer',icon='ADD')
        box.prop(s,'stack_on',icon='SORT_DESC')
        if s.stack_on:
            box.row(align=True).prop(s,'stack_mode',expand=True)
            if s.curved:box.label(text=_T('Not available on curved areas yet'),icon='ERROR')
            else:box.label(text=_T('Layer %d · %s'%(len(stack_chain(a))+1,'fills the gaps below' if s.stack_mode=='FILL' else 'lies on the layers below')),icon='INFO')
        else:box.label(text=_T('Add Layer = more posters in the gaps'))

    def draw_overlap(self,l,ui,s,a):
        body=ui_section(l,ui,'overlap','Overlap','SELECT_INTERSECT')   # After Rotation
        if not body:return
        if s.layout in ('RANDOM','PACK'):
            body.prop(s,'allow_overlap')
            if s.allow_overlap:body.prop(s,'overlap_ratio')
        else:body.label(text=_T('This layout always overlaps'),icon='INFO')
        if s.allow_overlap or s.layout in ('GRID','RAIL') or s.stack_on or pressers(a):
            col=body.column(align=True);col.prop(s,'grid_conform')
            if s.grid_conform:col.prop(s,'grid_stiffness')
            col.prop(s,'overlap_depth',text=_T('Gap Between Papers'))
            col=body.column(align=True);col.prop(s,'press')
            if s.press:col.prop(s,'press_strength');col.prop(s,'press_falloff')

    def draw_repeat(self,l,ui,s):
        body=ui_section(l,ui,'repeat','Reuse Posters','DUPLICATE',toggle=(s,'repeat'))
        if not body:return
        if not s.repeat:
            body.label(text=_T('Tick to use posters more than once'),icon='INFO');return
        body.prop(s,'repeat_limited')
        if not s.repeat_limited:
            body.label(text=_T('Repeats as far as count and space allow'));return
        col=body.column(align=True)
        col.label(text=_T('Max copies by poster size'))
        col.label(text=_T('0 = smallest · 1 = largest'))
        for i,rule in enumerate(s.repeat_ranges):
            row=body.row(align=True)
            lower=s.repeat_ranges[i-1].upper if i else 0.
            row.label(text=_T('%.3g ~'%lower))
            if i==len(s.repeat_ranges)-1:row.label(text=_T('1'))
            else:row.prop(rule,'upper',text=_T(''))
            row.prop(rule,'limit',text=_T(''))
            cell=row.row(align=True);cell.enabled=len(s.repeat_ranges)>1
            op=cell.operator('poster_scatter.repeat_range',text=_T(''),icon='REMOVE');op.action='REMOVE';op.index=i
        body.operator('poster_scatter.repeat_range',text=_T('Add Range'),icon='ADD').action='ADD'
        body.label(text=_T('Limit 0 keeps that size out'))
        if s.manual:body.label(text=_T('Pinned posters count too'))

    def draw_paint(self,l,ui,s,a):
        body=ui_section(l,ui,'paint','Paint Where Posters Go','BRUSH_DATA')
        if not body:return
        if a.mode=='VERTEX_PAINT':
            r=body.row();r.scale_y=1.3;r.operator('poster_scatter.paint_end',text=_T('Finish Painting'),icon='CHECKMARK')
        col=body.column(align=True)
        row=col.row(align=True)
        for label in ('Add','Erase'):row.operator('poster_scatter.paint',text=_T(label)).kind=label
        row=col.row(align=True)
        row.operator('poster_scatter.fill',text=_T('Fill All'),icon='BRUSH_DATA')
        row.operator('poster_scatter.invert',text=_T('Invert'),icon='ARROW_LEFTRIGHT')
        body.label(text=_T('White = posters · black = none'),icon='INFO')
        col=body.column(align=True);col.label(text=_T('Mix which poster lands where'))
        row=col.row(align=True)
        for label in ('Seed','Reset Seed'):row.operator('poster_scatter.paint',text=_T(label)).kind=label
        row=body.row(align=True)
        row.operator('poster_scatter.view',text=_T('Show Colors')).colors=True
        row.operator('poster_scatter.view',text=_T('Show Posters')).colors=False
        attr=a.data.color_attributes.active_color
        if attr:body.label(text=_T('Showing: '+{MASK:'Where posters go',GROUP:'Poster size',SEED:'Seed'}.get(attr.name,attr.name)))
        body.label(text=_T('Shift + stroke: soft blend'))

    def draw_manual(self,l,ui,s):
        body=ui_section(l,ui,'manual','Place Specific Posters','RESTRICT_SELECT_OFF')
        if not body:return
        r=body.row();r.scale_y=1.5;r.operator('poster_scatter.grab',icon='EYEDROPPER')
        body.label(text=_T('Click any poster on the wall · then move · R rotate · S scale'),icon='INFO')
        body.label(text=_T('When placed, the other posters re-arrange around it'),icon='BLANK1')
        if s.get('ps_frozen_key'):
            row=body.row(align=True);row.label(text=_T('Other posters kept in place'),icon='LOCKED')
            row.operator('poster_scatter.unfreeze',text=_T(''),icon='FILE_REFRESH')
        body.separator()
        if s.collection:body.prop_search(s,'manual_poster',s.collection,'all_objects',text=_T('Poster'))
        else:body.prop(s,'manual_poster')
        row=body.row(align=True);row.prop(s,'manual_angle',text=_T('Angle'));row.prop(s,'manual_scale',text=_T('Scale'))
        body.prop(s,'manual_no_lift')
        r=body.row();r.scale_y=1.3;r.enabled=s.manual_poster is not None
        r.operator('poster_scatter.place',icon='RESTRICT_SELECT_OFF')
        body.label(text=_T('R rotate · S scale · +/- 10% · Esc'),icon='INFO')
        if not s.manual:return
        body.label(text=_T('%d pinned · auto posters move around them'%len(s.manual)))
        for n,item in enumerate(s.manual):
            box=body.box();row=box.row(align=True)
            row.label(text=_T('%d. %s'%(n+1,item.poster.name if item.poster else '(none)')))
            op=row.operator('poster_scatter.place',text=_T(''),icon='ORIENTATION_GIMBAL');op.index=n
            op=row.operator('poster_scatter.remove_manual',text=_T(''),icon='X');op.index=n
            row=box.row(align=True);row.prop(item,'angle',text=_T('Angle'));row.prop(item,'scale',text=_T('Scale'))
            row=box.row(align=True);row.prop(item,'sx',text=_T('Width'));row.prop(item,'sy',text=_T('Height'))
            box.prop(item,'no_lift',text=_T('No Lift (flat)'))

    def draw_finish(self,l,ui,s):
        body=ui_section(l,ui,'finish','Finish','CHECKMARK')
        if not body:return
        if s.output:body.prop(s.output,'hide_viewport',text=_T('Hide These Posters'),icon='HIDE_ON' if s.output.hide_viewport else 'HIDE_OFF',toggle=True)
        r=body.row();r.scale_y=1.8;r.operator('poster_scatter.bake',icon='MESH_DATA')
        body.label(text=_T('Makes a normal mesh (final step)'),icon='INFO')

    def draw_help(self,l,ui):
        body=ui_section(l,ui,'help','Quick Guide','QUESTION')
        if not body:return
        col=body.column(align=True)
        for t in ('Posters: the collection to use','Layout: how papers spread out','Rotation: X Y Z on, then Random',
                  'Paper Lift: curl the edges','Overlap: papers rest on each other','Paint: where posters may go',
                  'Place: pin a chosen poster','Finish: turn it into a mesh','Changes apply live (Live on)'):
            col.label(text=_T(t),icon='DOT')



class PS_Prefs(bpy.types.AddonPreferences):
    bl_idname=__name__
    language:EnumProperty(name='Language',items=[('EN','English','English interface'),('KO','한국어','한국어 인터페이스')],
        default=_i18n_lang(),update=_i18n_lang_changed,description='Interface language of Print & Pin (Poster Print and Poster Pin)')
    def draw(self,context):
        col=self.layout.column()
        col.prop(self,'language')
        if self.language=='KO':
            col.label(text='패널·편집기·메시지는 바로 바뀌어요. 버튼 이름과 툴팁 일부는 블렌더를 다시 시작하면 바뀌어요.',icon='INFO')
        else:
            col.label(text='Panels, the editor and messages switch right away. Some button names and tooltips change after restarting Blender.',icon='INFO')
        col.label(text='Print & Pin · by G_ni')

CLASSES=[PS_Prefs,PS_RepeatRange,PS_Placement,PS_Settings,PS_OT_repeat_range,PS_OT_reset,PS_OT_pin_reset,PS_OT_add_clip,PS_OT_sticky_preset,PS_OT_create,PS_OT_add_layer,PS_OT_update,PS_OT_bake,PS_OT_place,PS_OT_grab,PS_OT_unfreeze,PS_OT_remove_manual,PS_OT_view,PS_OT_paint_end,PS_OT_paint,PS_OT_fill,PS_OT_invert,PS_OT_rail_edges,PS_OT_create_rail,PS_UIState,PS_OT_ui_fold,PS_PT_panel]
def register():
    for cls in CLASSES:
        if cls.__doc__ and not getattr(cls,'bl_description',None) and _i18n_lang()=='KO':
            try:cls.__doc__=_T(cls.__doc__)
            except Exception:pass
        bpy.utils.register_class(cls)
    bpy.types.Object.poster_scatter=PointerProperty(type=PS_Settings)
    bpy.types.Scene.poster_scatter_setup=PointerProperty(type=PS_Settings)
    bpy.types.Scene.ps_ui=PointerProperty(type=PS_UIState)
    bpy.types.Scene.ps_show_results=BoolProperty(name=_T('Show Placed Posters'),default=True,update=ps_show_results_changed,
        description=_T('Shows or hides the placed posters of every scatter in the viewport (renders are not affected)'))
    for h in (bpy.app.handlers.load_post,bpy.app.handlers.undo_post,bpy.app.handlers.redo_post):
        if _ps_fix_areas not in h:h.append(_ps_fix_areas)
    bpy.app.timers.register(lambda:(_ps_fix_areas(),None)[1],first_interval=.5)
    bpy.types.Scene.ps_show_areas=BoolProperty(name=_T('Show Scatter Area Bounds'),default=False,update=ps_show_areas_changed,
        description=_T('Shows or hides the scatter area bounds (wire boxes) on poles and walls in the viewport. They never appear in renders.'))
    bpy.types.Scene.ps_show_sources=BoolProperty(name=_T('Show Source Posters'),default=False,update=ps_show_sources_changed,
        description=_T('Shows the original poster gallery after it has been scattered. Off hides it in the viewport and in renders; placed posters are not affected.'))
    if not bpy.app.timers.is_registered(tick):bpy.app.timers.register(tick,first_interval=.4,persistent=True)
def unregister():
    for placer in list(PLACERS):placer.finish()
    if bpy.app.timers.is_registered(tick):bpy.app.timers.unregister(tick)
    if bpy.app.timers.is_registered(paint_watch):bpy.app.timers.unregister(paint_watch)
    if bpy.app.timers.is_registered(_ps_fix_areas_now):bpy.app.timers.unregister(_ps_fix_areas_now)
    SIGNATURES.clear()
    del bpy.types.Scene.poster_scatter_setup;del bpy.types.Object.poster_scatter
    for name in ('ps_ui','ps_show_results'):
        if hasattr(bpy.types.Scene,name):delattr(bpy.types.Scene,name)
    if hasattr(bpy.types.Scene,'ps_show_areas'):del bpy.types.Scene.ps_show_areas
    if hasattr(bpy.types.Scene,'ps_show_sources'):del bpy.types.Scene.ps_show_sources
    for h in (bpy.app.handlers.load_post,bpy.app.handlers.undo_post,bpy.app.handlers.redo_post):
        for f in [f for f in h if getattr(f,'__name__','')=='_ps_fix_areas']:h.remove(f)
    for cls in reversed(CLASSES):bpy.utils.unregister_class(cls)
if __name__=='__main__':register()



