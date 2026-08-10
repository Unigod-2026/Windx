import client from "./client";

export interface Customer {
  id: number;
  name: string;
  code: string;
  contact: string | null;
  status: "active" | "disabled";
  logo_path: string | null;
  logo_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface CustomerList {
  items: Customer[];
  total: number;
  page: number;
  size: number;
}

export interface CustomerCreatePayload {
  name: string;
  code: string;
  contact?: string | null;
}

export interface CustomerUpdatePayload {
  name?: string;
  contact?: string | null;
  status?: "active" | "disabled";
}

export const listCustomers = (params: { page?: number; size?: number }) =>
  client.get<CustomerList>("/customers", { params }).then((r) => r.data);

export const createCustomer = (data: CustomerCreatePayload) =>
  client.post<Customer>("/customers", data).then((r) => r.data);

export const updateCustomer = (id: number, data: CustomerUpdatePayload) =>
  client.put<Customer>(`/customers/${id}`, data).then((r) => r.data);

export const uploadLogo = (id: number, file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return client
    .post<Customer>(`/customers/${id}/logo`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

export const deleteCustomer = (id: number) =>
  client.delete(`/customers/${id}`).then((r) => r.data);
