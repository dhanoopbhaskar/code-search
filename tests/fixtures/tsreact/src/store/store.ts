import { loadArticles } from './articlesSlice';

export const store = {
  dispatch: (value: unknown) => value,
};

export const dispatchArticles = () => store.dispatch(loadArticles());
