"""Genre edit styles: how each kind of video is actually cut.

Requirement 2 asks for ten named styles, each carrying its own cut tempo,
captions, font direction, transitions, music, colour, photo motion and how
much text and effect it tolerates. This module is that table.

Two things keep it from being the fixed-template trap the brief warns
against:

* it produces an `EditDirective`, which `edit_director.py` then *adjusts*
  from the material analysis and the genre profile before anything acts on
  it - the preset is the starting point, not the answer;
* the styles are mapped onto Trend Intelligence's existing content genres
  rather than replacing them, so a travel video still gets the measured
  travel profile (duration, scene seconds, BPM range) laid over the travel
  edit style.

The numbers are format conventions, and the module says so: nothing here is
a measurement, and `decided_by` stays "defaults" until something with real
evidence changes it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.edit_style import (
    STYLE_LABELS,
    AudioPolicy,
    ColorGrade,
    EditDirective,
    FontDirection,
    PhotoMotionPolicy,
    StoryBeat,
    SubtitlePolicy,
    TransitionPolicy,
)

# ---------------------------------------------------------------- colours

# Colour looks, as small eq/colorbalance nudges. Requirement 13: unify the
# look without destroying the material's own colour, so nothing here moves
# saturation more than 15% or contrast more than 12%.
COLOR_GRADES: dict[str, ColorGrade] = {
    "none": ColorGrade(id="none", label="無補正", reason="素材の色をそのまま使います"),
    "clean": ColorGrade(
        id="clean",
        label="Clean",
        brightness=0.012,
        contrast=1.045,
        saturation=1.05,
        gamma=1.0,
        reason="素材の色を保ったまま、わずかに締めて見やすくします",
    ),
    "warm": ColorGrade(
        id="warm",
        label="Warm",
        brightness=0.02,
        contrast=1.05,
        saturation=1.10,
        gamma=1.02,
        highlight_red=0.06,
        reason="暖色寄りにして、料理や人の肌を美味しそう・健康的に見せます",
    ),
    "cinematic": ColorGrade(
        id="cinematic",
        label="Cinematic",
        brightness=-0.012,
        contrast=1.10,
        saturation=0.93,
        gamma=0.97,
        shadow_blue=0.07,
        highlight_red=0.03,
        reason="影を少し青く、彩度を落として映画的な階調にします",
    ),
    "bright": ColorGrade(
        id="bright",
        label="Bright",
        brightness=0.04,
        contrast=1.03,
        saturation=1.12,
        gamma=1.05,
        reason="明るく軽やかに持ち上げ、日常の映像を朗らかに見せます",
    ),
    "moody": ColorGrade(
        id="moody",
        label="Moody",
        brightness=-0.03,
        contrast=1.12,
        saturation=0.88,
        gamma=0.95,
        shadow_blue=0.10,
        reason="全体を落とし込んで、静かで重心の低い雰囲気にします",
    ),
    "retro": ColorGrade(
        id="retro",
        label="Retro",
        brightness=0.015,
        contrast=0.94,
        saturation=0.90,
        gamma=1.04,
        highlight_red=0.08,
        reason="コントラストと彩度を落として、褪せたフィルム調にします",
    ),
    "travel": ColorGrade(
        id="travel",
        label="Travel",
        brightness=0.025,
        contrast=1.07,
        saturation=1.14,
        gamma=1.01,
        shadow_blue=0.04,
        reason="空と海の青、緑の発色を少し強めて旅の映像らしくします",
    ),
}


def grade(grade_id: str, strength: float = 1.0) -> ColorGrade:
    """A named grade, optionally weakened.

    `strength` scales every term toward identity rather than clamping them,
    so "warmを半分だけ" is a real, describable decision instead of an
    on/off switch.
    """
    base = COLOR_GRADES.get(grade_id, COLOR_GRADES["clean"])
    strength = max(0.0, min(2.0, strength))
    if abs(strength - 1.0) < 0.01:
        return base.model_copy(deep=True)
    return ColorGrade(
        id=base.id,
        label=base.label,
        brightness=round(base.brightness * strength, 4),
        contrast=round(1.0 + (base.contrast - 1.0) * strength, 4),
        saturation=round(1.0 + (base.saturation - 1.0) * strength, 4),
        gamma=round(1.0 + (base.gamma - 1.0) * strength, 4),
        shadow_blue=round(base.shadow_blue * strength, 4),
        highlight_red=round(base.highlight_red * strength, 4),
        strength=strength,
        reason=base.reason,
    )


# ----------------------------------------------------------- story beats

# Structures requirement 8 names, plus the ones the other styles need. Each
# beat's `share` is a fraction of total runtime; they are renormalised when
# beats are dropped for want of material, so a four-photo video does not
# get a six-act structure.
STORY_STRUCTURES: dict[str, list[StoryBeat]] = {
    "shorts": [
        StoryBeat(id="hook", label="Hook", purpose="最初の1〜3秒で一番強い画を見せる", share=0.10),
        StoryBeat(id="intro", label="Introduction", purpose="何の動画かを一言で示す", share=0.15),
        StoryBeat(id="development", label="Development", purpose="内容を展開する", share=0.40),
        StoryBeat(id="highlight", label="Highlight", purpose="山場を見せる", share=0.22),
        StoryBeat(id="ending", label="Ending", purpose="余韻かひと押しで終える", share=0.13),
    ],
    "travel": [
        StoryBeat(id="arrival", label="Arrival", purpose="到着・出発の高揚を出す", share=0.14),
        StoryBeat(id="location", label="Location", purpose="どこにいるかを見せる", share=0.20),
        StoryBeat(id="experience", label="Experience", purpose="そこで何をしたかを見せる", share=0.24),
        StoryBeat(id="food", label="Food", purpose="食べたもの・味わいを見せる", share=0.16),
        StoryBeat(id="highlight", label="Highlight", purpose="一番の絶景や瞬間", share=0.16),
        StoryBeat(id="ending", label="Ending", purpose="帰路や余韻で締める", share=0.10),
    ],
    "vlog": [
        StoryBeat(id="opening", label="Opening", purpose="その日の空気感を出す", share=0.15),
        StoryBeat(id="daily", label="Daily", purpose="日常の流れを追う", share=0.35),
        StoryBeat(id="moment", label="Moment", purpose="今日いちばんの出来事", share=0.30),
        StoryBeat(id="ending", label="Ending", purpose="静かに終わる", share=0.20),
    ],
    "tutorial": [
        StoryBeat(id="problem", label="課題", purpose="何が問題なのかを示す", share=0.15),
        StoryBeat(id="overview", label="全体像", purpose="やることの全体を先に見せる", share=0.15),
        StoryBeat(id="steps", label="手順", purpose="順を追って説明する", share=0.50),
        StoryBeat(id="result", label="結果", purpose="できあがりを見せて締める", share=0.20),
    ],
    "documentary": [
        StoryBeat(id="setup", label="導入", purpose="対象と状況を提示する", share=0.20),
        StoryBeat(id="context", label="背景", purpose="背景を積み上げる", share=0.30),
        StoryBeat(id="turn", label="転", purpose="視点が変わる出来事", share=0.30),
        StoryBeat(id="close", label="結", purpose="結論と余韻", share=0.20),
    ],
    "food": [
        StoryBeat(id="finish", label="完成カット", purpose="完成形を先に見せる", share=0.12),
        StoryBeat(id="ingredients", label="材料", purpose="素材を見せる", share=0.18),
        StoryBeat(id="cooking", label="調理", purpose="作る過程を見せる", share=0.42),
        StoryBeat(id="taste", label="実食", purpose="食べる・味わう", share=0.28),
    ],
    "story3": [
        StoryBeat(id="hook", label="掴み", purpose="つかむ", share=0.20),
        StoryBeat(id="body", label="展開", purpose="見せる", share=0.55),
        StoryBeat(id="ending", label="オチ", purpose="終える", share=0.25),
    ],
}


# ------------------------------------------------------------- the styles


@dataclass(frozen=True)
class EditStyle:
    """One named way of cutting a video."""

    id: str
    label: str
    description: str
    # Content genres (services/trends/genre.py ids) this style is the
    # natural edit style for.
    genres: tuple[str, ...]
    tempo: str
    scene_seconds: float
    scene_seconds_min: float
    scene_seconds_max: float
    hook_seconds: float
    story: str
    subtitle: SubtitlePolicy
    font: FontDirection
    transitions: TransitionPolicy
    photo_motion: PhotoMotionPolicy
    color_grade: str
    color_strength: float
    audio: AudioPolicy
    mood: str
    energy_curve: tuple[str, ...] = ()
    # 0.0-1.0. How much decoration this style tolerates - drives SFX
    # density and caption animation, and is what stops "エフェクトが多い＝
    # 高品質" from creeping back in.
    effect_appetite: float = 0.4
    notes: tuple[str, ...] = field(default_factory=tuple)


STYLES: tuple[EditStyle, ...] = (
    EditStyle(
        id="vlog",
        label="Vlog",
        description="日常の空気感を、字幕を盛らずに見せる",
        genres=("vlog",),
        tempo="medium",
        scene_seconds=3.4,
        scene_seconds_min=2.2,
        scene_seconds_max=6.0,
        hook_seconds=3.0,
        story="vlog",
        subtitle=SubtitlePolicy(
            density="low",
            coverage=0.45,
            position="bottom",
            style="outline",
            size_scale=0.88,
            emphasis=False,
            animation="fade",
            reason="Vlogは字幕を出しすぎると生活感が消えるため、必要な場面だけに絞ります",
        ),
        font=FontDirection(
            wanted=["clean", "sans", "modern", "regular", "medium"],
            avoid=["decorative", "impact", "mono", "black"],
            luxury=0.25,
            casual=0.6,
            cinematic=0.25,
            impact=0.25,
            weight_min=400,
            weight_max=700,
            min_readability=62,
            reason="細めで癖のないゴシックが、日常の映像を邪魔しません",
        ),
        transitions=TransitionPolicy(
            default="cut",
            allowed=["cut", "dissolve", "fade"],
            max_ratio=0.20,
            duration=0.45,
            strong="fade",
            reason="基本はカット。時間が飛ぶところだけ短いディゾルブでつなぎます",
        ),
        photo_motion=PhotoMotionPolicy(
            intensity=0.75,
            prefer=["zoom_in", "pan_left", "pan_right"],
            reason="写真はゆっくり動かして、スナップの空気を保ちます",
        ),
        color_grade="clean",
        color_strength=0.9,
        audio=AudioPolicy(
            bgm_mood="gentle",
            bgm_bpm_range=[82.0, 108.0],
            bgm_volume=0.85,
            keep_ambience=0.8,
            sfx_per_minute=3.0,
            narration_rate=-1,
            reason="環境音を残し、BGMは控えめに。効果音はほとんど使いません",
        ),
        mood="穏やか・素朴",
        energy_curve=("落ち着き", "ゆるやかな高まり", "余韻"),
        effect_appetite=0.2,
        notes=("字幕は全カットには付けません", "効果音は最小限です"),
    ),
    EditStyle(
        id="travel",
        label="Travel",
        description="景色の切り替わりで見せる、テンポのある旅動画",
        genres=("travel",),
        tempo="medium",
        scene_seconds=2.8,
        scene_seconds_min=1.8,
        scene_seconds_max=5.0,
        hook_seconds=2.5,
        story="travel",
        subtitle=SubtitlePolicy(
            density="low",
            coverage=0.55,
            position="bottom",
            style="outline",
            size_scale=0.95,
            emphasis=True,
            emphasis_scale=1.15,
            animation="fade",
            reason="地名と一言だけを出し、景色を字幕で潰さないようにします",
        ),
        font=FontDirection(
            wanted=["modern", "clean", "sans", "medium", "bold"],
            avoid=["decorative", "mono", "handwritten"],
            luxury=0.4,
            casual=0.4,
            cinematic=0.5,
            impact=0.45,
            weight_min=500,
            weight_max=800,
            min_readability=64,
            reason="景色の上でも読める、抜けの良いモダンなサンセリフを選びます",
        ),
        transitions=TransitionPolicy(
            default="cut",
            allowed=["cut", "dissolve", "slide_left", "zoom", "dip_to_black"],
            max_ratio=0.30,
            duration=0.5,
            strong="dip_to_black",
            reason="場所が変わるところにだけ切り替えを入れ、それ以外はカットで繋ぎます",
        ),
        photo_motion=PhotoMotionPolicy(
            intensity=1.15,
            prefer=["zoom_in", "pan_right", "pan_left", "zoom_out"],
            reason="風景写真は広がりが出るよう、ゆっくり大きめに動かします",
        ),
        color_grade="travel",
        color_strength=1.0,
        audio=AudioPolicy(
            bgm_mood="bright",
            bgm_bpm_range=[100.0, 126.0],
            bgm_volume=1.0,
            keep_ambience=0.65,
            sfx_per_minute=6.0,
            narration_rate=0,
            reason="明るめのBGMを主役に、波音などの環境音も残します",
        ),
        mood="爽やか・開放的",
        energy_curve=("期待", "高揚", "満たされ", "余韻"),
        effect_appetite=0.45,
        notes=("場所が変わるところだけTransitionを使います",),
    ),
    EditStyle(
        id="cinematic",
        label="Cinematic",
        description="長めのカットと低彩度で、映画的に見せる",
        genres=(),
        tempo="slow",
        scene_seconds=4.5,
        scene_seconds_min=3.0,
        scene_seconds_max=9.0,
        hook_seconds=4.0,
        story="documentary",
        subtitle=SubtitlePolicy(
            density="minimal",
            coverage=0.3,
            position="bottom",
            style="plain",
            size_scale=0.8,
            emphasis=False,
            animation="fade",
            letter_spacing=1.5,
            reason="字幕は最小限に。字間を空けた細い文字で、画の邪魔をしません",
        ),
        font=FontDirection(
            wanted=["serif", "elegant", "clean", "light", "regular"],
            avoid=["decorative", "rounded", "impact", "mono"],
            luxury=0.7,
            casual=0.1,
            cinematic=0.95,
            impact=0.15,
            weight_min=300,
            weight_max=600,
            min_readability=55,
            reason="明朝・セリフ系の細身が、シネマティックな画に合います",
        ),
        transitions=TransitionPolicy(
            default="cut",
            allowed=["cut", "dissolve", "dip_to_black", "fade"],
            max_ratio=0.35,
            duration=0.8,
            strong="dip_to_black",
            reason="長めのディゾルブと黒落ちで、時間の流れを見せます",
        ),
        photo_motion=PhotoMotionPolicy(
            intensity=0.6,
            prefer=["zoom_in", "pan_left"],
            reason="写真はごくゆっくり。動きが目立つと画の重さが消えます",
        ),
        color_grade="cinematic",
        color_strength=1.0,
        audio=AudioPolicy(
            bgm_mood="emotional",
            bgm_bpm_range=[70.0, 96.0],
            bgm_volume=0.95,
            keep_ambience=0.85,
            sfx_per_minute=2.0,
            narration_rate=-2,
            narration_style="落ち着いた低めの語り",
            reason="ゆっくりした語りと静かな音楽。効果音はほぼ使いません",
        ),
        mood="静謐・重厚",
        energy_curve=("静けさ", "緊張", "解放", "余韻"),
        effect_appetite=0.15,
        notes=("カットは長め、字幕は最小限です",),
    ),
    EditStyle(
        id="food",
        label="Food",
        description="寄りのカットと暖色で、美味しそうに見せる",
        genres=("food",),
        tempo="fast",
        scene_seconds=2.3,
        scene_seconds_min=1.5,
        scene_seconds_max=4.5,
        hook_seconds=2.0,
        story="food",
        subtitle=SubtitlePolicy(
            density="high",
            coverage=0.9,
            position="bottom",
            style="box",
            size_scale=1.0,
            emphasis=True,
            emphasis_scale=1.25,
            animation="pop",
            reason="材料や手順は文字で補う必要があるため、字幕は多めに出します",
        ),
        font=FontDirection(
            wanted=["rounded", "bold", "friendly", "sans", "medium"],
            avoid=["mono", "decorative", "light"],
            luxury=0.2,
            casual=0.75,
            cinematic=0.1,
            impact=0.6,
            weight_min=600,
            weight_max=900,
            min_readability=70,
            reason="丸みのある太いゴシックが、料理の写真と相性がよく読みやすいです",
        ),
        transitions=TransitionPolicy(
            default="cut",
            allowed=["cut", "dissolve", "zoom"],
            max_ratio=0.20,
            duration=0.3,
            strong="dissolve",
            reason="調理は流れが命なのでカット主体。工程の切れ目だけ短く繋ぎます",
        ),
        photo_motion=PhotoMotionPolicy(
            intensity=1.0,
            prefer=["zoom_in"],
            reason="料理写真は寄っていくと美味しそうに見えます",
        ),
        color_grade="warm",
        color_strength=1.0,
        audio=AudioPolicy(
            bgm_mood="warm",
            bgm_bpm_range=[95.0, 122.0],
            bgm_volume=0.9,
            keep_ambience=0.9,
            sfx_per_minute=8.0,
            narration_rate=0,
            reason="調理音を残すため環境音を強めに、BGMは下げ気味にします",
        ),
        mood="温かい・食欲をそそる",
        energy_curve=("期待", "集中", "完成", "満足"),
        effect_appetite=0.5,
    ),
    EditStyle(
        id="tutorial",
        label="Tutorial / 解説",
        description="読ませる字幕と、迷わない構成",
        genres=("education", "tech", "business"),
        tempo="medium",
        scene_seconds=3.6,
        scene_seconds_min=2.4,
        scene_seconds_max=7.0,
        hook_seconds=3.0,
        story="tutorial",
        subtitle=SubtitlePolicy(
            density="high",
            coverage=0.95,
            position="bottom",
            style="box",
            size_scale=0.98,
            emphasis=True,
            emphasis_scale=1.2,
            animation="fade",
            max_lines=2,
            reason="解説は音を切って見られるため、ほぼ全カットに字幕を入れます",
        ),
        font=FontDirection(
            wanted=["readable", "universal_design", "sans", "medium", "bold", "clean"],
            avoid=["decorative", "handwritten", "italic", "light"],
            luxury=0.2,
            casual=0.35,
            cinematic=0.1,
            impact=0.45,
            weight_min=500,
            weight_max=800,
            min_readability=78,
            reason="読み取りやすさが最優先なので、UD系・可読性の高い書体を選びます",
        ),
        transitions=TransitionPolicy(
            default="cut",
            allowed=["cut", "dissolve", "slide_left"],
            max_ratio=0.18,
            duration=0.35,
            strong="dissolve",
            reason="話が切り替わる箇所だけ。装飾的な切り替えは理解を妨げます",
        ),
        photo_motion=PhotoMotionPolicy(
            intensity=0.5,
            prefer=["zoom_in"],
            reason="図や画面は動かしすぎると読めなくなるため、動きは最小にします",
        ),
        color_grade="clean",
        color_strength=0.7,
        audio=AudioPolicy(
            bgm_mood="calm",
            bgm_bpm_range=[85.0, 110.0],
            bgm_volume=0.7,
            keep_ambience=0.4,
            sfx_per_minute=4.0,
            narration_rate=1,
            narration_style="はっきりした説明口調",
            reason="声が最優先。BGMは小さく、ナレーション中は大きく下げます",
        ),
        mood="明快・落ち着き",
        energy_curve=("疑問", "理解", "納得"),
        effect_appetite=0.25,
    ),
    EditStyle(
        id="entertainment",
        label="Entertainment",
        description="テンポと勢いで見せる、賑やかな編集",
        genres=("entertainment", "game", "sports"),
        tempo="fast",
        scene_seconds=2.0,
        scene_seconds_min=1.3,
        scene_seconds_max=4.0,
        hook_seconds=2.0,
        story="shorts",
        subtitle=SubtitlePolicy(
            density="high",
            coverage=0.9,
            position="middle",
            style="outline",
            size_scale=1.1,
            emphasis=True,
            emphasis_scale=1.35,
            animation="pop",
            reason="テロップで勢いを作るため、大きめ・強調ありで出します",
        ),
        font=FontDirection(
            wanted=["impact", "bold", "black", "sans"],
            avoid=["light", "mono", "serif"],
            luxury=0.1,
            casual=0.7,
            cinematic=0.1,
            impact=0.95,
            weight_min=700,
            weight_max=900,
            min_readability=68,
            reason="太く強い書体でテロップに勢いを持たせます",
        ),
        transitions=TransitionPolicy(
            default="cut",
            allowed=["cut", "zoom", "slide_left", "slide_right", "push_left", "dissolve"],
            max_ratio=0.35,
            duration=0.25,
            strong="zoom",
            reason="展開が変わるところで短く強い切り替えを使います",
        ),
        photo_motion=PhotoMotionPolicy(
            intensity=1.35,
            prefer=["zoom_in", "zoom_out", "pan_right"],
            reason="写真も速く大きく動かして、映像の勢いに合わせます",
        ),
        color_grade="bright",
        color_strength=1.0,
        audio=AudioPolicy(
            bgm_mood="energetic",
            bgm_bpm_range=[120.0, 155.0],
            bgm_volume=1.05,
            keep_ambience=0.5,
            sfx_per_minute=12.0,
            narration_rate=2,
            reason="速いBGMと効果音でテンポを作ります",
        ),
        mood="賑やか・勢いがある",
        energy_curve=("驚き", "加速", "頂点", "オチ"),
        effect_appetite=0.85,
    ),
    EditStyle(
        id="shorts",
        label="SNS Shorts",
        description="冒頭勝負・縦型・音なし視聴前提",
        genres=("news", "unknown"),
        tempo="fast",
        scene_seconds=2.4,
        scene_seconds_min=1.5,
        scene_seconds_max=4.5,
        hook_seconds=2.0,
        story="shorts",
        subtitle=SubtitlePolicy(
            density="high",
            coverage=0.9,
            position="middle",
            style="outline",
            size_scale=1.05,
            emphasis=True,
            emphasis_scale=1.25,
            animation="pop",
            reason="音を切って見られる前提なので、字幕を大きく確実に出します",
        ),
        font=FontDirection(
            wanted=["bold", "impact", "sans", "clean", "modern"],
            avoid=["light", "mono", "handwritten"],
            luxury=0.2,
            casual=0.6,
            cinematic=0.15,
            impact=0.8,
            weight_min=600,
            weight_max=900,
            min_readability=72,
            reason="小さい画面でも一瞬で読める太めのサンセリフを選びます",
        ),
        transitions=TransitionPolicy(
            default="cut",
            allowed=["cut", "dissolve", "zoom", "slide_up"],
            max_ratio=0.22,
            duration=0.28,
            strong="zoom",
            reason="尺が短いので基本はカット。展開の節目だけ短く切り替えます",
        ),
        photo_motion=PhotoMotionPolicy(
            intensity=1.2,
            prefer=["zoom_in", "zoom_out"],
            reason="縦型では寄り引きの動きが最も効きます",
        ),
        color_grade="bright",
        color_strength=0.9,
        audio=AudioPolicy(
            bgm_mood="modern",
            bgm_bpm_range=[105.0, 135.0],
            bgm_volume=1.0,
            keep_ambience=0.5,
            sfx_per_minute=10.0,
            narration_rate=1,
            reason="テンポの良いBGMで、冒頭から引き込みます",
        ),
        mood="キャッチー・軽快",
        energy_curve=("掴み", "展開", "山場", "締め"),
        effect_appetite=0.65,
    ),
    EditStyle(
        id="documentary",
        label="Documentary",
        description="事実を積む構成と、抑えた画づくり",
        genres=(),
        tempo="slow",
        scene_seconds=4.8,
        scene_seconds_min=3.0,
        scene_seconds_max=10.0,
        hook_seconds=4.0,
        story="documentary",
        subtitle=SubtitlePolicy(
            density="medium",
            coverage=0.7,
            position="bottom",
            style="plain",
            size_scale=0.85,
            emphasis=False,
            animation="fade",
            reason="語りを補う位置づけなので、控えめな文字で下に置きます",
        ),
        font=FontDirection(
            wanted=["serif", "readable", "medium", "clean"],
            avoid=["decorative", "rounded", "impact"],
            luxury=0.45,
            casual=0.15,
            cinematic=0.6,
            impact=0.25,
            weight_min=400,
            weight_max=700,
            min_readability=68,
            reason="明朝寄りの落ち着いた書体が、記録映像の空気に合います",
        ),
        transitions=TransitionPolicy(
            default="cut",
            allowed=["cut", "dissolve", "dip_to_black"],
            max_ratio=0.30,
            duration=0.7,
            strong="dip_to_black",
            reason="章が変わるところで黒に落として、話の区切りを作ります",
        ),
        photo_motion=PhotoMotionPolicy(
            intensity=0.55,
            prefer=["zoom_in", "pan_right"],
            reason="資料写真はゆっくり寄る／流すのが基本です",
        ),
        color_grade="moody",
        color_strength=0.7,
        audio=AudioPolicy(
            bgm_mood="calm",
            bgm_bpm_range=[68.0, 92.0],
            bgm_volume=0.75,
            keep_ambience=0.9,
            sfx_per_minute=1.5,
            narration_rate=-2,
            narration_style="淡々とした語り",
            reason="現場音を尊重し、BGMと効果音は最小限にします",
        ),
        mood="静か・事実的",
        energy_curve=("提示", "積み上げ", "転換", "結論"),
        effect_appetite=0.1,
    ),
    EditStyle(
        id="luxury",
        label="Luxury",
        description="余白と細い文字で、上質さを出す",
        genres=("beauty",),
        tempo="slow",
        scene_seconds=4.0,
        scene_seconds_min=2.6,
        scene_seconds_max=8.0,
        hook_seconds=3.0,
        story="story3",
        subtitle=SubtitlePolicy(
            density="minimal",
            coverage=0.35,
            position="bottom",
            style="plain",
            size_scale=0.78,
            emphasis=False,
            animation="fade",
            letter_spacing=2.5,
            reason="字間を広く取った細い文字を少量だけ。情報量を絞ることが上質さになります",
        ),
        font=FontDirection(
            wanted=["serif", "elegant", "light", "clean", "regular"],
            avoid=["rounded", "impact", "black", "decorative", "mono"],
            luxury=1.0,
            casual=0.05,
            cinematic=0.6,
            impact=0.1,
            weight_min=300,
            weight_max=550,
            min_readability=52,
            reason="細身のセリフ／明朝が高級感を作ります",
        ),
        transitions=TransitionPolicy(
            default="cut",
            allowed=["cut", "dissolve", "fade"],
            max_ratio=0.30,
            duration=0.9,
            strong="fade",
            reason="ゆっくりしたディゾルブだけを使い、動きの強い切り替えは避けます",
        ),
        photo_motion=PhotoMotionPolicy(
            intensity=0.5,
            prefer=["zoom_in"],
            reason="ごく緩やかな寄りだけ。速い動きは安っぽく見えます",
        ),
        color_grade="cinematic",
        color_strength=0.75,
        audio=AudioPolicy(
            bgm_mood="emotional",
            bgm_bpm_range=[70.0, 95.0],
            bgm_volume=0.85,
            keep_ambience=0.5,
            sfx_per_minute=1.0,
            narration_rate=-2,
            narration_style="ゆっくり、間を取った語り",
            reason="静かな音楽と間。効果音はほぼ使いません",
        ),
        mood="上質・落ち着き",
        energy_curve=("静", "美", "余韻"),
        effect_appetite=0.1,
    ),
    EditStyle(
        id="casual",
        label="Casual",
        description="肩の力を抜いた、親しみのある編集",
        genres=("pet",),
        tempo="medium",
        scene_seconds=2.8,
        scene_seconds_min=1.8,
        scene_seconds_max=5.0,
        hook_seconds=2.5,
        story="story3",
        subtitle=SubtitlePolicy(
            density="medium",
            coverage=0.75,
            position="bottom",
            style="outline",
            size_scale=1.0,
            emphasis=True,
            emphasis_scale=1.2,
            animation="pop",
            reason="読みやすい大きさで、要所だけ強調します",
        ),
        font=FontDirection(
            wanted=["rounded", "friendly", "sans", "medium", "bold"],
            avoid=["mono", "serif", "decorative"],
            luxury=0.1,
            casual=0.95,
            cinematic=0.05,
            impact=0.5,
            weight_min=500,
            weight_max=800,
            min_readability=70,
            reason="丸ゴシック系の親しみやすい書体を選びます",
        ),
        transitions=TransitionPolicy(
            default="cut",
            allowed=["cut", "dissolve", "slide_left", "zoom"],
            max_ratio=0.25,
            duration=0.35,
            strong="dissolve",
            reason="基本はカット。話が変わるところだけ軽く切り替えます",
        ),
        photo_motion=PhotoMotionPolicy(
            intensity=1.0,
            prefer=["zoom_in", "pan_left", "pan_right"],
            reason="写真は自然な速さで動かします",
        ),
        color_grade="bright",
        color_strength=0.85,
        audio=AudioPolicy(
            bgm_mood="playful",
            bgm_bpm_range=[100.0, 132.0],
            bgm_volume=0.95,
            keep_ambience=0.75,
            sfx_per_minute=7.0,
            narration_rate=0,
            reason="明るいBGMに、控えめな効果音を添えます",
        ),
        mood="親しみやすい・軽やか",
        energy_curve=("なごみ", "楽しさ", "余韻"),
        effect_appetite=0.45,
    ),
)

STYLE_BY_ID: dict[str, EditStyle] = {s.id: s for s in STYLES}

# Content genre -> edit style. Built from each style's own `genres` tuple so
# the two can never disagree.
_GENRE_TO_STYLE: dict[str, str] = {}
for _style in STYLES:
    for _genre in _style.genres:
        _GENRE_TO_STYLE.setdefault(_genre, _style.id)


def style_for_genre(genre: str) -> EditStyle:
    """The edit style a content genre defaults to.

    "shorts" is the fallback rather than an error: an unclassified brief is
    still a short-form video, and the shorts style is the one that assumes
    the least about the content.
    """
    return STYLE_BY_ID.get(_GENRE_TO_STYLE.get(genre, ""), STYLE_BY_ID["shorts"])


# Words in a brief that name an edit style directly. Checked before the
# genre mapping, because "沖縄旅行をシネマティックに" is an explicit request
# for the cinematic style over the travel one.
_STYLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "cinematic": ("シネマティック", "映画風", "映画のよう", "cinematic", "filmic", "シネマ"),
    "luxury": ("高級", "ラグジュアリー", "上質", "luxury", "エレガント", "上品"),
    "documentary": ("ドキュメンタリー", "記録", "documentary", "密着"),
    "vlog": ("vlog", "ブイログ", "日常", "ルーティン", "暮らし"),
    "travel": ("旅行", "旅", "travel", "trip", "観光", "絶景"),
    "food": ("料理", "レシピ", "グルメ", "food", "cooking", "飯", "スイーツ"),
    "tutorial": ("解説", "説明", "使い方", "チュートリアル", "tutorial", "howto", "入門", "講座"),
    "entertainment": ("エンタメ", "面白", "おもしろ", "バラエティ", "ゲーム実況", "盛り上"),
    "casual": ("カジュアル", "ゆるい", "ゆるく", "casual", "気軽"),
    "shorts": ("shorts", "ショート", "tiktok", "reels", "リール", "バズ"),
}


def style_from_instruction(instruction: str) -> str | None:
    """An edit style the user named outright, or None.

    Longest match wins, so "シネマティックなVlog" resolves to cinematic
    rather than to whichever keyword happened to be checked first.
    """
    text = (instruction or "").casefold()
    if not text.strip():
        return None
    best: tuple[int, str] | None = None
    for style_id, words in _STYLE_KEYWORDS.items():
        for word in words:
            if word.casefold() in text and (best is None or len(word) > best[0]):
                best = (len(word), style_id)
    return best[1] if best else None


def story_for(style: EditStyle) -> list[StoryBeat]:
    """A fresh copy of this style's structure, safe to mutate."""
    beats = STORY_STRUCTURES.get(style.story) or STORY_STRUCTURES["story3"]
    return [b.model_copy(deep=True) for b in beats]


def base_directive(style: EditStyle) -> EditDirective:
    """The style's own preset, as an `EditDirective` with nothing applied yet."""
    return EditDirective(
        style=style.id,  # type: ignore[arg-type]
        style_label=STYLE_LABELS.get(style.id, style.label),
        mood=style.mood,
        tempo=style.tempo,  # type: ignore[arg-type]
        scene_seconds=style.scene_seconds,
        scene_seconds_min=style.scene_seconds_min,
        scene_seconds_max=style.scene_seconds_max,
        hook_seconds=style.hook_seconds,
        energy_curve=list(style.energy_curve),
        story=story_for(style),
        subtitle=style.subtitle.model_copy(deep=True),
        font=style.font.model_copy(deep=True),
        transitions=style.transitions.model_copy(deep=True),
        photo_motion=style.photo_motion.model_copy(deep=True),
        color=grade(style.color_grade, style.color_strength),
        audio=style.audio.model_copy(deep=True),
        decided_by="defaults",
        notes=list(style.notes),
    )


def style_list() -> list[dict]:
    """The styles, for the UI's "編集スタイル" picker."""
    return [
        {
            "id": s.id,
            "label": STYLE_LABELS.get(s.id, s.label),
            "description": s.description,
            "tempo": s.tempo,
            "scene_seconds": s.scene_seconds,
            "subtitle_density": s.subtitle.density,
            "color_grade": s.color_grade,
            "bgm_mood": s.audio.bgm_mood,
            "genres": list(s.genres),
        }
        for s in STYLES
    ]
