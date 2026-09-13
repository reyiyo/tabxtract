// TabXtract - GPL-3.0-or-later. See LICENSE.
interface Props {
  onAccept: () => void;
}

/**
 * First-run notice. Shown once, and it is not an EULA: there is nothing to
 * agree to contractually, it is information worth having before pasting a URL.
 */
export function LegalNotice({ onAccept }: Props) {
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h2>Before you start</h2>
        <p>
          TabXtract is for personal use on material you have the right to use. Tablature is
          frequently copyrighted, and many transcriptions are commercial products.
        </p>
        <p>
          Downloading from video platforms may conflict with their terms of service,
          depending on jurisdiction and circumstances. You are responsible for what you
          process with this tool.
        </p>
        <p className="hint">
          The app has no sharing features and no gallery: nothing you extract leaves this
          machine.
        </p>
        <button onClick={onAccept}>Got it</button>
      </div>
    </div>
  );
}
