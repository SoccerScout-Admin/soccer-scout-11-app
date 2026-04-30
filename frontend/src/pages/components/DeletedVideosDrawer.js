import { Trash } from '@phosphor-icons/react';

const DeletedVideosDrawer = ({ open, deletedVideos, onClose, onRestore }) => {
  if (!open) return null;
  return (
    <div data-testid="deleted-drawer-overlay" onClick={onClose}
      className="fixed inset-0 bg-black/70 z-[200] flex items-center justify-center px-4">
      <div onClick={(e) => e.stopPropagation()}
        className="bg-[#141414] border border-white/10 max-w-lg w-full max-h-[70vh] flex flex-col">
        <div className="p-5 border-b border-white/10">
          <h3 className="text-xl font-bold tracking-wider uppercase" style={{ fontFamily: 'Bebas Neue' }}>
            Recover Deleted Video
          </h3>
          <p className="text-xs text-[#A3A3A3] mt-1">
            Videos deleted in the last 24 hours can be restored. Clips and AI analysis from before deletion are not recoverable.
          </p>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          {deletedVideos.length === 0 ? (
            <p className="text-center text-sm text-[#666] py-8">No recently deleted videos for this match.</p>
          ) : (
            <div className="space-y-2">
              {deletedVideos.map(v => (
                <div key={v.id} data-testid={`deleted-video-${v.id}`}
                  className="bg-[#0A0A0A] border border-white/10 p-3 flex items-center gap-3">
                  <Trash size={20} className="text-[#666] flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-white truncate">{v.original_filename || v.id}</div>
                    <div className="text-[10px] text-[#666] tracking-wider">
                      Deleted {new Date(v.deleted_at).toLocaleString()}
                    </div>
                  </div>
                  <button data-testid={`restore-${v.id}-btn`} onClick={() => onRestore(v.id)}
                    className="text-xs px-3 py-1.5 bg-[#10B981]/15 text-[#10B981] hover:bg-[#10B981]/25 transition-colors font-bold tracking-wider uppercase">
                    Restore
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="p-4 border-t border-white/10">
          <button onClick={onClose}
            className="w-full py-2.5 border border-white/10 text-[#A3A3A3] hover:text-white text-xs font-bold tracking-wider uppercase">
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

export default DeletedVideosDrawer;
