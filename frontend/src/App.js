import React from 'react';
import Header from './components/Header';
import VideoUpload from './components/VideoUpload';
import SearchControls from './components/SearchControls';
import Tabs from './components/Tabs';
import TabContent from './components/TabContent';
import { useVideoProcessing } from './hooks/useVideoProcessing';

function App() {
  const {
    videos,
    processLogs,
    searchQuery,
    searchType,
    editableResults,
    nGrams,
    transcripts,
    activeTab,
    setActiveTab,
    exportedVideoPath,
    isLoading,
    isUploading,
    handleFileUpload,
    handleImportSRT,
    handleTranscribe,
    handleSearch,
    onDragEnd,
    handleNGrams,
    handleExport,
    removeResult,
    isResultContained,
    handleSearchQueryChange,
    handleSearchTypeChange
  } = useVideoProcessing();

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container mx-auto px-4 py-8">
        <div className="bg-white shadow-xl rounded-2xl overflow-hidden">
          <Header isLoading={isLoading} />
          <div className="grid md:grid-cols-2 gap-6 p-6">
            <div className="space-y-6">
              <VideoUpload
                handleFileUpload={handleFileUpload}
                isUploading={isUploading}
                videos={videos}
              />
              <div className="grid grid-cols-2 gap-4">
                <button
                  onClick={handleTranscribe}
                  disabled={videos.length === 0}
                  className="bg-blue-500 text-white px-4 py-2 rounded-lg hover:bg-blue-600 transition disabled:opacity-50"
                >
                  Transcribe
                </button>
                <label
                  className={`bg-yellow-500 text-white px-4 py-2 rounded-lg hover:bg-yellow-600 transition text-center cursor-pointer ${videos.length === 0 ? 'opacity-50 pointer-events-none' : ''}`}
                >
                  Import SRT
                  <input
                    type="file"
                    accept=".srt"
                    onChange={handleImportSRT}
                    className="hidden"
                  />
                </label>
              </div>
              <SearchControls
                handleSearchQueryChange={handleSearchQueryChange}
                handleSearchTypeChange={handleSearchTypeChange}
                handleSearch={handleSearch}
                handleExport={handleExport}
                searchQuery={searchQuery}
                searchType={searchType}
                videos={videos}
                editableResults={editableResults}
              />
            </div>
            <div className="bg-white border rounded-xl shadow-md">
              <Tabs activeTab={activeTab} setActiveTab={setActiveTab} />
              <TabContent
                activeTab={activeTab}
                editableResults={editableResults}
                onDragEnd={onDragEnd}
                isResultContained={isResultContained}
                removeResult={removeResult}
                nGrams={nGrams}
                handleNGrams={handleNGrams}
                transcripts={transcripts}
                exportedVideoPath={exportedVideoPath}
                searchType={searchType}
                processLogs={processLogs}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;