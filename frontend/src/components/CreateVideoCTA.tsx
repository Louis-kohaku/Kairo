import { formatTime } from "../utils/format";

interface Props {
  sceneCount: number;
  clipCount: number;
  timelineDuration: number;
  ffmpegAvailable: boolean;
  blockedReason: string | null;
  busy: boolean;
  onStart: () => void;
}

export default function CreateVideoCTA({
  sceneCount,
  clipCount,
  timelineDuration,
  ffmpegAvailable,
  blockedReason,
  busy,
  onStart,
}: Props) {
  const disabled = busy || !ffmpegAvailable || !!blockedReason;

  return (
    <div className="create-video-cta">
      <div className="create-video-cta-icon">🎬</div>
      <h2>動画制作の準備完了</h2>
      {sceneCount > 0 && <p>{sceneCount}個のシーンを企画済み</p>}
      <p>
        タイムラインに{clipCount}個のクリップ・約{formatTime(timelineDuration)}の動画を配置済み
      </p>

      {!ffmpegAvailable && (
        <div className="create-video-cta-warning">
          ⚠ FFmpegが見つかりません。設定から確認してください。
        </div>
      )}
      {blockedReason && <div className="create-video-cta-warning">⚠ {blockedReason}</div>}

      <button className="primary create-video-cta-button" onClick={onStart} disabled={disabled}>
        🎬 動画を作成
      </button>
    </div>
  );
}
