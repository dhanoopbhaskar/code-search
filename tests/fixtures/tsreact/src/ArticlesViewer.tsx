import React from 'react';
import { ArticleList } from './features/ArticleList';
import { loadArticles } from './store/articlesSlice';

export const ArticlesViewer = () => {
  const articles = loadArticles();
  return <main><ArticleList /></main>;
};

export default ArticlesViewer;
