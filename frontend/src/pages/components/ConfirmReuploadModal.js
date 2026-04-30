import { Warning, Trash } from '@phosphor-icons/react';

const ConfirmReuploadModal = ({ open, deleting, onConfirm, onCancel }) => {
  if (!open) return null;
  return (
    <div data-testid="confirm-reupload-overlay" onClick={() => !deleting && onCancel()}
      className="fixed inset-0 bg-black/70 z-[200] flex items-center justify-center px-4">
      <div onClick={(e) => e.stopPropagation()}
        className="bg-[#141414] border border-[#EF4444]/30 max-w-md w-full p-6">
        <div className="flex items-start gap-3 mb-3">
          <Warning size={28} className="text-[#EF4444] flex-shrink-0" weight="fill" />
          <div className="flex-1">
            <h3 className="text-xl font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>
              Replace Match Video?
            </h3>
            <p className="text-sm text-[#A3A3A3] mt-2 leading-relaxed">
              The current video and everything derived from it will be permanently removed:
            </p>
            <ul className="text-xs text-[#A3A3A3] mt-2 space-y-1 list-disc pl-5">
              <li>The video file and any chunked upload data</li>
              <li>All clips created from this video</li>
              <li>AI timeline markers and analyses</li>
            </ul>
            <p className="text-sm text-white mt-3 font-medium">
              The match itself, your roster, and folder placement stay intact. You'll be able to upload a fresh video right away.
            </p>
          </div>
        </div>
        <div className="flex gap-3 mt-5">
          <button data-testid="confirm-reupload-btn" onClick={onConfirm} disabled={deleting}
            className="flex-1 bg-[#EF4444] hover:bg-[#DC2626] disabled:opacity-50 text-white py-3 font-bold tracking-wider uppercase text-xs transition-colors flex items-center justify-center gap-2">
            {deleting ? 'Deleting…' : <><Trash size={14} weight="bold" /> Delete Video</>}
          </button>
          <button onClick={onCancel} disabled={deleting}
            className="px-5 py-3 border border-white/10 text-[#A3A3A3] hover:text-white hover:bg-[#1F1F1F] text-xs font-bold uppercase">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmReuploadModal;
