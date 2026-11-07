import React from 'react'
import { ExternalLink, FileText, Bookmark } from 'lucide-react'
import type { Citation } from '../types/api'
import { getDocumentUrl } from '../services/api'

interface CitationCardProps {
  citation: Citation
}

export const CitationCard: React.FC<CitationCardProps> = ({ citation }) => {
  return (
    <div className="bg-blue-50/60 hover:bg-blue-50/90 border border-blue-200/80 rounded-xl p-3.5 transition-colors shadow-xs">
      {/* Header: Title, Article & Page Badge */}
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2 mb-2">
        <div className="flex items-start gap-2 min-w-0">
          <div className="p-1.5 rounded-lg bg-blue-100 text-blue-700 shrink-0 mt-0.5">
            <FileText className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <h4 className="text-xs sm:text-sm font-bold text-gray-800 leading-snug truncate" title={citation.title}>
              {citation.title}
            </h4>
            {citation.article && (
              <span className="inline-flex items-start gap-1 text-[11px] font-medium text-blue-700 mt-0.5 break-words">
                <Bookmark className="w-3 h-3 text-blue-500 shrink-0 mt-0.5" />
                {citation.article}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between sm:justify-end gap-2 shrink-0">
          {citation.page != null && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold bg-blue-100/80 text-blue-800 border border-blue-200">
              صفحة {citation.page}
            </span>
          )}
          <a
            href={getDocumentUrl(citation.document_id, citation.page)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-lg bg-white hover:bg-blue-600 text-blue-700 hover:text-white border border-blue-300 hover:border-transparent transition-all shadow-xs active:scale-95 group"
            title="فتح المستند الأصلي في علامة تبويب جديدة"
          >
            <span>فتح المصدر</span>
            <ExternalLink className="w-3.5 h-3.5 transition-transform group-hover:-translate-x-0.5 group-hover:-translate-y-0.5" />
          </a>
        </div>
      </div>

      {/* Quote Snippet */}
      {citation.quote && (
        <div className="relative mt-2 pt-2 border-t border-blue-100/80">
          <blockquote className="text-xs text-gray-700 leading-relaxed italic bg-white/70 border-r-2 border-blue-400 p-2.5 rounded-l-lg pr-3 break-words">
            &ldquo;{citation.quote}&rdquo;
          </blockquote>
        </div>
      )}
    </div>
  )
}
