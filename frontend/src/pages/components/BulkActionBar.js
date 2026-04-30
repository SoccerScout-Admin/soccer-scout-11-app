const BulkActionBar = ({ selectedCount, bulkBusy, folders, onMove, onSetCompetition, onDelete }) => (
  <div data-testid="bulk-action-bar"
    className="sticky top-0 z-30 bg-[#FBBF24]/15 border border-[#FBBF24]/30 px-4 py-3 flex items-center gap-3 mb-4 -mx-4 md:mx-0 backdrop-blur">
    <span className="text-sm font-bold tracking-wider uppercase text-[#FBBF24]">
      {selectedCount} selected
    </span>
    <div className="ml-auto flex flex-wrap gap-2">
      <select data-testid="bulk-move-select"
        disabled={selectedCount === 0 || bulkBusy}
        onChange={(e) => { if (e.target.value !== '__none__') onMove(e.target.value === '' ? null : e.target.value); e.target.value = '__none__'; }}
        defaultValue="__none__"
        className="bg-[#0A0A0A] border border-white/10 text-xs text-[#A3A3A3] px-3 py-2 focus:outline-none">
        <option value="__none__" disabled>Move to folder…</option>
        <option value="">No folder (root)</option>
        {folders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
      </select>
      <button data-testid="bulk-set-competition-btn" onClick={onSetCompetition}
        disabled={selectedCount === 0 || bulkBusy}
        className="text-xs px-3 py-2 bg-[#007AFF]/15 text-[#007AFF] hover:bg-[#007AFF]/25 disabled:opacity-50 font-bold tracking-wider uppercase">
        Set Competition
      </button>
      <button data-testid="bulk-delete-btn" onClick={onDelete}
        disabled={selectedCount === 0 || bulkBusy}
        className="text-xs px-3 py-2 bg-[#EF4444]/15 text-[#EF4444] hover:bg-[#EF4444]/25 disabled:opacity-50 font-bold tracking-wider uppercase">
        Delete
      </button>
    </div>
  </div>
);

export default BulkActionBar;
