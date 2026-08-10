import { Navigate, useParams } from "react-router-dom";

/**
 * The project editor is now a popup modal opened from the list page; this
 * dedicated route exists only so legacy / shared links like
 * ``/admin/projects/42`` still land on the editor. We redirect to the list
 * with a search-param that auto-opens the modal for that project id.
 */
export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const target = `/admin/projects?open=${encodeURIComponent(id ?? "")}`;
  return <Navigate to={target} replace />;
}