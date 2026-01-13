package it.bastio.graphql;

import it.bastio.model.Film;
import it.bastio.service.FilmService;
import jakarta.inject.Inject;
import org.eclipse.microprofile.graphql.GraphQLApi;
import org.eclipse.microprofile.graphql.Mutation;
import org.eclipse.microprofile.graphql.Query;

import java.util.List;

@GraphQLApi
public class FilmGraphQLResource {

    @Inject
    FilmService filmService;

    @Query
    public List<Film> getFilms() {
        return filmService.getFilms();
    }

    @Query
    public Film findFilmById(Integer id) {
        return filmService.getFilmById(id);
    }

    @Mutation
    public Film addFilm(Film film) {
        return filmService.addFilm(film);
    }

    @Mutation
    public Film removeFilm(Integer id) {
        return filmService.removeFilm(id);
    }
}
