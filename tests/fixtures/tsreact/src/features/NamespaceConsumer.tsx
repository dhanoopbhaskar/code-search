import * as articles from '../store/articlesSlice';

export const NamespaceConsumer = () => {
  return articles.loadArticles();
};
