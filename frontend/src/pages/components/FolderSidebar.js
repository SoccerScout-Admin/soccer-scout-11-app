import { Plus, VideoCamera, FolderSimple, FolderOpen, Lock, DotsThreeVertical, PencilSimple, Trash, CaretRight, CaretDown, ShareNetwork, ChartLineUp } from '@phosphor-icons/react';

const FolderMenu = ({ folder, onEdit, onShare, onTrends, onDelete, onClose }) => (
  <div className="absolute right-0 top-full z-50 bg-[#1F1F1F] border border-white/10 py-1 min-w-[120px] shadow-xl"
    onClick={(e) => e.stopPropagation()}>
    <button data-testid={`edit-folder-${folder.id}-btn`}
      onClick={() => { onEdit(folder); onClose(); }}
      className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-[#A3A3A3] hover:bg-white/5 hover:text-white">
      <PencilSimple size={12} /> Rename
    </button>
    {!folder.is_private && (
      <button data-testid={`share-folder-${folder.id}-btn`}
        onClick={() => { onShare(folder); onClose(); }}
        className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-white/5 ${
          folder.share_token ? 'text-[#4ADE80]' : 'text-[#A3A3A3] hover:text-white'
        }`}>
        <ShareNetwork size={12} /> {folder.share_token ? 'Sharing On' : 'Share'}
      </button>
    )}
    <button data-testid={`folder-trends-${folder.id}-btn`}
      onClick={() => { onTrends(folder.id); onClose(); }}
      className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-[#A855F7] hover:bg-[#A855F7]/10">
      <ChartLineUp size={12} /> Season Trends
    </button>
    <button data-testid={`delete-folder-${folder.id}-btn`}
      onClick={() => { onDelete(folder.id); onClose(); }}
      className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-[#EF4444] hover:bg-[#EF4444]/10">
      <Trash size={12} /> Delete
    </button>
  </div>
);

const FolderSidebar = ({
  matches,
  flatFolderList,
  selectedFolderId,
  setSelectedFolderId,
  folderMenuId,
  setFolderMenuId,
  onToggleExpand,
  onOpenNewFolder,
  onEditFolder,
  onShareFolder,
  onTrendsFolder,
  onDeleteFolder,
}) => {
  const unfolderedCount = matches.filter(m => !m.folder_id).length;
  return (
    <aside className="w-full lg:w-64 lg:flex-shrink-0" data-testid="folder-sidebar">
      <div className="bg-[#141414] border border-white/10 p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xs font-bold tracking-[0.2em] uppercase text-[#A3A3A3]">Folders</h3>
          <button data-testid="create-folder-btn" onClick={onOpenNewFolder}
            className="p-1 hover:bg-[#1F1F1F] transition-colors text-[#007AFF]">
            <Plus size={18} weight="bold" />
          </button>
        </div>

        <button data-testid="all-matches-folder-btn" onClick={() => setSelectedFolderId(null)}
          className={`w-full flex items-center gap-2 px-3 py-2 text-left text-sm transition-colors mb-1 ${
            selectedFolderId === null ? 'bg-[#007AFF]/10 text-[#007AFF] border-l-2 border-[#007AFF]' : 'text-[#A3A3A3] hover:bg-[#1F1F1F] hover:text-white'
          }`}>
          <FolderOpen size={18} />
          <span className="flex-1 truncate">All Matches</span>
          <span className="text-[10px] opacity-60">{matches.length}</span>
        </button>

        <button data-testid="unfoldered-matches-btn" onClick={() => setSelectedFolderId('__none__')}
          className={`w-full flex items-center gap-2 px-3 py-2 text-left text-sm transition-colors mb-2 ${
            selectedFolderId === '__none__' ? 'bg-[#007AFF]/10 text-[#007AFF] border-l-2 border-[#007AFF]' : 'text-[#A3A3A3] hover:bg-[#1F1F1F] hover:text-white'
          }`}>
          <VideoCamera size={18} />
          <span className="flex-1 truncate">Unsorted</span>
          <span className="text-[10px] opacity-60">{unfolderedCount}</span>
        </button>

        <div className="border-t border-white/5 pt-2">
          {flatFolderList.map(folder => {
            const matchCount = matches.filter(m => m.folder_id === folder.id).length;
            const isSelected = selectedFolderId === folder.id;
            return (
              <div key={folder.id} style={{ paddingLeft: `${folder.depth * 12}px` }}>
                <div data-testid={`folder-item-${folder.id}`}
                  className={`flex items-center gap-1 px-2 py-1.5 text-sm transition-colors group relative cursor-pointer ${
                    isSelected ? 'bg-[#007AFF]/10 text-[#007AFF]' : 'text-[#A3A3A3] hover:bg-[#1F1F1F] hover:text-white'
                  }`}>
                  {folder.hasChildren ? (
                    <button onClick={(e) => { e.stopPropagation(); onToggleExpand(folder.id); }}
                      className="p-0.5 hover:bg-white/10 transition-colors flex-shrink-0">
                      {folder.isExpanded ? <CaretDown size={12} /> : <CaretRight size={12} />}
                    </button>
                  ) : <div className="w-4" />}
                  <button className="flex-1 flex items-center gap-2 min-w-0 text-left"
                    onClick={() => setSelectedFolderId(folder.id)}>
                    <FolderSimple size={16} className="flex-shrink-0" />
                    <span className="truncate text-xs">{folder.name}</span>
                    {folder.is_private && <Lock size={10} className="text-[#EF4444] flex-shrink-0" />}
                    {folder.share_token && <ShareNetwork size={10} className="text-[#4ADE80] flex-shrink-0" />}
                    <span className="text-[10px] opacity-50 ml-auto flex-shrink-0">{matchCount}</span>
                  </button>
                  <button data-testid={`folder-menu-${folder.id}-btn`}
                    onClick={(e) => { e.stopPropagation(); setFolderMenuId(folderMenuId === folder.id ? null : folder.id); }}
                    className="p-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 hover:bg-white/10">
                    <DotsThreeVertical size={14} />
                  </button>
                  {folderMenuId === folder.id && (
                    <FolderMenu folder={folder}
                      onEdit={onEditFolder} onShare={onShareFolder}
                      onTrends={onTrendsFolder} onDelete={onDeleteFolder}
                      onClose={() => setFolderMenuId(null)} />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </aside>
  );
};

export default FolderSidebar;
