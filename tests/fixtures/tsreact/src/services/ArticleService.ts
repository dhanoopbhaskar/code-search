import { Loader } from './Loader';

export class ArticleService {
  private loader: Loader;

  constructor(loader: Loader) {
    this.loader = loader;
  }

  load(): string {
    this.helper();
    return this.loader.fetch();
  }

  helper(): void {}
}

const service: ArticleService = new ArticleService(new Loader());

export const loadThroughService = () => service.load();

export const loadViaParam = (loader: Loader) => loader.fetch();
