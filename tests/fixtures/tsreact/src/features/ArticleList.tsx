import React from 'react';
import { Button } from '@/components';
import { loadArticles } from '../store/articlesSlice';

export const ArticleList = () => {
  const articles = loadArticles();
  return (
    <ul>
      {articles.map((article) => (
        <li key={article.id}>
          <Button label={article.title} />
        </li>
      ))}
    </ul>
  );
};
