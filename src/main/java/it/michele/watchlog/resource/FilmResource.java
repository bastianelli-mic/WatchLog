package it.michele.watchlog.resource;

import io.smallrye.mutiny.Uni;
import it.michele.watchlog.model.Film;
import it.michele.watchlog.resource.dto.FilmDTO;
import it.michele.watchlog.service.FilmService;
import jakarta.inject.Inject;
import jakarta.ws.rs.*;
import jakarta.ws.rs.core.MediaType;

@Path("/film")
public class FilmResource {

    @Inject
    FilmService filmService;

    @Path("/create")
    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    public Uni<Void> create(FilmDTO filmDTO){
        return filmService.create(new Film(filmDTO.getTitle()));
    }

    @Path("/get/{id}")
    @GET
    @Produces(MediaType.APPLICATION_JSON)
    public Uni<Film> get(@PathParam("id") long id){
        return filmService.findById(id);
    }
}
