// First-run guidance (design doc section 41): shown once so a brand-new
// user knows the whole rest of the setup is optional before they even see
// the wizard. Purely a local UI flag - never sent anywhere.
const SEEN_KEY = "kairo_seen_intro";

export function hasSeenIntro(): boolean {
  try {
    return localStorage.getItem(SEEN_KEY) === "1";
  } catch {
    return true;
  }
}

function markSeen() {
  try {
    localStorage.setItem(SEEN_KEY, "1");
  } catch {
    /* ignore - private browsing etc. */
  }
}

export default function WelcomeIntro({ onStart }: { onStart: () => void }) {
  return (
    <div className="welcome-intro">
      <h1>Kairoへようこそ</h1>
      <p>最初は3つ選ぶだけでOKです。</p>
      <ol className="welcome-intro-steps">
        <li>① 動画タイプ</li>
        <li>② 動画の長さ</li>
        <li>③ 縦 / 横</li>
      </ol>
      <p className="generation-engine-reason">AIや細かい設定はKairoが自動で最適化します。あとから自由に変更できます。</p>
      <button
        className="primary"
        onClick={() => {
          markSeen();
          onStart();
        }}
      >
        はじめる
      </button>
    </div>
  );
}
