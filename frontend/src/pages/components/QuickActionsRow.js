/**
 * Two big tap-action cards at the top of the dashboard:
 *   - New Video Upload — opens the create match modal, intent = upload film
 *   - Create Game — opens the create match modal, intent = manual entry
 *
 * Both currently trigger the same modal (the modal already supports both
 * upload-then-analyze AND manual-result flows). The split here is mostly
 * about reducing decision fatigue for first-time coaches.
 */
import { VideoCamera, PlayCircle } from '@phosphor-icons/react';

const QuickActionsRow = ({ onCreate }) => (
  <section data-testid="quick-actions-row" className="mb-6">
    <p className="text-[10px] tracking-[0.3em] uppercase font-bold text-[#A3A3A3] mb-3">
      Recent Activities
    </p>
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
      <button
        data-testid="quick-action-upload"
        type="button"
        onClick={onCreate}
        className="group flex items-center gap-4 bg-gradient-to-br from-[#0F1A2E] to-[#141414] border border-[#007AFF]/30 hover:border-[#007AFF] hover:from-[#142850] transition-all p-5 sm:p-6 text-left">
        <div className="w-14 h-14 bg-[#007AFF]/15 border border-[#007AFF]/30 flex items-center justify-center flex-shrink-0 group-hover:bg-[#007AFF]/25 transition-colors">
          <VideoCamera size={28} weight="bold" className="text-[#007AFF]" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xl sm:text-2xl font-bold uppercase tracking-wider text-white mb-0.5" style={{ fontFamily: 'Bebas Neue' }}>
            New Video Upload
          </div>
          <div className="text-xs text-[#A3A3A3] truncate">
            Upload match film & run AI breakdown
          </div>
        </div>
        <span className="hidden sm:inline-flex bg-[#007AFF] text-white px-4 py-2 text-[10px] font-bold tracking-wider uppercase group-hover:bg-[#005bb5] transition-colors">
          Upload Now
        </span>
      </button>

      <button
        data-testid="quick-action-create-game"
        type="button"
        onClick={onCreate}
        className="group flex items-center gap-4 bg-gradient-to-br from-[#0F1F1A] to-[#141414] border border-[#10B981]/30 hover:border-[#10B981] hover:from-[#0F2A1E] transition-all p-5 sm:p-6 text-left">
        <div className="w-14 h-14 bg-[#10B981]/15 border border-[#10B981]/30 flex items-center justify-center flex-shrink-0 group-hover:bg-[#10B981]/25 transition-colors">
          <PlayCircle size={28} weight="bold" className="text-[#10B981]" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xl sm:text-2xl font-bold uppercase tracking-wider text-white mb-0.5" style={{ fontFamily: 'Bebas Neue' }}>
            Create Game
          </div>
          <div className="text-xs text-[#A3A3A3] truncate">
            Log a match — with or without video
          </div>
        </div>
        <span className="hidden sm:inline-flex bg-[#10B981] text-black px-4 py-2 text-[10px] font-bold tracking-wider uppercase group-hover:bg-[#0e9d6c] transition-colors">
          Create
        </span>
      </button>
    </div>
  </section>
);

export default QuickActionsRow;
