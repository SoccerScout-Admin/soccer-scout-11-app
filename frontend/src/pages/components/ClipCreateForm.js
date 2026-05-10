const ClipCreateForm = ({
  clipFormData,
  setClipFormData,
  currentTimestamp,
  players,
  selectedClipPlayerIds,
  setSelectedClipPlayerIds,
  onClose,
  onSave,
}) => (
  <div className="bg-[#111] rounded-lg border border-white/10 p-5">
    <div className="flex items-center justify-between mb-4">
      <h3 className="text-sm font-semibold" style={{ fontFamily: 'Space Grotesk' }}>Create Clip</h3>
      <button data-testid="close-clip-form-btn" onClick={onClose} className="text-[#666] hover:text-white">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
      </button>
    </div>
    <div className="space-y-3">
      <input data-testid="clip-title-input" type="text" placeholder="Clip title" value={clipFormData.title}
        onChange={(e) => setClipFormData({ ...clipFormData, title: e.target.value })}
        className="w-full bg-white/5 rounded-lg text-white px-3 py-2.5 text-sm border border-white/10 focus:border-[#007AFF] focus:outline-none" />
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-[10px] text-[#666] uppercase tracking-wider mb-1">Start</label>
          <div className="flex gap-2">
            <input data-testid="clip-start-time-input" type="number" step="0.1" value={clipFormData.start_time}
              onChange={(e) => setClipFormData({ ...clipFormData, start_time: parseFloat(e.target.value) || 0 })}
              className="flex-1 bg-white/5 rounded-lg text-white px-3 py-2 text-sm border border-white/10 focus:border-[#007AFF] focus:outline-none" />
            <button data-testid="set-start-time-btn" onClick={() => setClipFormData({ ...clipFormData, start_time: currentTimestamp })}
              className="px-3 py-2 rounded-lg bg-white/10 text-[#007AFF] text-xs font-medium hover:bg-white/15 transition-colors">Now</button>
          </div>
        </div>
        <div>
          <label className="block text-[10px] text-[#666] uppercase tracking-wider mb-1">End</label>
          <div className="flex gap-2">
            <input data-testid="clip-end-time-input" type="number" step="0.1" value={clipFormData.end_time}
              onChange={(e) => setClipFormData({ ...clipFormData, end_time: parseFloat(e.target.value) || 0 })}
              className="flex-1 bg-white/5 rounded-lg text-white px-3 py-2 text-sm border border-white/10 focus:border-[#007AFF] focus:outline-none" />
            <button data-testid="set-end-time-btn" onClick={() => setClipFormData({ ...clipFormData, end_time: currentTimestamp })}
              className="px-3 py-2 rounded-lg bg-white/10 text-[#007AFF] text-xs font-medium hover:bg-white/15 transition-colors">Now</button>
          </div>
        </div>
      </div>
      <select data-testid="clip-type-select" value={clipFormData.clip_type}
        onChange={(e) => setClipFormData({ ...clipFormData, clip_type: e.target.value })}
        className="w-full bg-white/5 rounded-lg text-white px-3 py-2.5 text-sm border border-white/10 focus:border-[#007AFF] focus:outline-none">
        <option value="highlight">Highlight</option>
        <option value="goal">Goal</option>
        <option value="save">Save</option>
        <option value="tactical">Tactical Play</option>
        <option value="mistake">Mistake</option>
      </select>
      <textarea data-testid="clip-description-input" placeholder="Description (optional)" value={clipFormData.description}
        onChange={(e) => setClipFormData({ ...clipFormData, description: e.target.value })}
        className="w-full bg-white/5 rounded-lg text-white px-3 py-2.5 text-sm border border-white/10 focus:border-[#007AFF] focus:outline-none resize-none" rows="2" />
      {players.length > 0 && (
        <div>
          <label className="block text-[10px] text-[#666] uppercase tracking-wider mb-1">Tag Players (optional)</label>
          <div className="flex flex-wrap gap-1.5 bg-white/5 rounded-lg p-2 border border-white/10 max-h-24 overflow-y-auto">
            {players.map(p => {
              const isSelected = selectedClipPlayerIds.includes(p.id);
              return (
                <button key={p.id} type="button" data-testid={`clip-player-tag-${p.id}`}
                  onClick={() => setSelectedClipPlayerIds(
                    isSelected ? selectedClipPlayerIds.filter(id => id !== p.id) : [...selectedClipPlayerIds, p.id]
                  )}
                  className={`px-2 py-1 text-[10px] font-medium transition-colors ${
                    isSelected ? 'bg-[#007AFF] text-white' : 'bg-white/5 text-[#888] hover:text-white hover:bg-white/10'
                  }`}>
                  #{p.number ?? '?'} {p.name}
                </button>
              );
            })}
          </div>
        </div>
      )}
      <button data-testid="save-clip-btn" onClick={onSave}
        className="w-full bg-[#007AFF] hover:bg-[#0066DD] text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-colors">
        Save Clip
      </button>
    </div>
  </div>
);

export default ClipCreateForm;
