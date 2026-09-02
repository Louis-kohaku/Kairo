export default function ReRenderBanner({ onGoToExport }: { onGoToExport: () => void }) {
  return (
    <div className="rerender-banner">
      <span>⚠ 変更内容があります。この内容をMP4に反映するには再レンダリングが必要です。</span>
      <button className="primary" onClick={onGoToExport}>
        再レンダリング
      </button>
    </div>
  );
}
